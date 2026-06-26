#!/usr/bin/env python3
"""grill — put it in the hot seat.

Hand it an ANSWER (and optionally the original question) and it cross-examines
it: hidden assumptions, missing edge cases, internal contradictions, unsupported
claims, overconfidence, and "what would change your mind?". It generates the
sharp follow-ups that attack the answer's weak points, then (optionally) runs
them against a model to see whether the answer holds up or cracks under
questioning. The stress-test you run on an answer before you trust it.

Cousin of strawman: strawman red-teams a PROMPT, grill cross-examines an ANSWER.

Usage:
    # works with any one of these keys (install that provider's SDK):
    export ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY, or GEMINI_API_KEY
    python3 grill.py answer.txt
    cat answer.txt | python3 grill.py
    python3 grill.py answer.txt --question "Is this migration safe?"
    python3 grill.py answer.txt --angles assumptions,sources
    python3 grill.py answer.txt --provider openai --model gpt-4o
    python3 grill.py answer.txt --dry-run     # no API key needed

Talks to Anthropic, OpenAI-compatible, and Gemini backends via each provider's
official SDK (anthropic / openai / google-genai), lazily imported (only --dry-run
needs nothing at all).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys

# --- llm backend ----------------------------------------------------------
# Self-contained multi-provider LLM client. Each provider's OFFICIAL SDK is
# imported lazily — only when that provider is actually used — so you install
# only the one you need (`pip install anthropic` / `openai` / `google-genai`).
# Inlined per trick on purpose: every trick stays a single self-contained file.
#
# Provider/model/key are resolved from --provider/--model or the environment:
#     ANTHROPIC_API_KEY -> anthropic  (ANTHROPIC_BASE_URL, ANTHROPIC_MODEL)
#     OPENAI_API_KEY    -> openai     (OPENAI_BASE_URL,    OPENAI_MODEL)
#     GEMINI_API_KEY    -> gemini     (GEMINI_BASE_URL,    GEMINI_MODEL)
#        (GOOGLE_API_KEY is accepted as an alias for GEMINI_API_KEY)
#     BOT_LLM_PROVIDER / BOT_LLM_MODEL force a provider / model across tricks.

_LLM_PROVIDERS = ("anthropic", "openai", "gemini")
_LLM_DEFAULT_MODEL = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-4o",
    "gemini": "gemini-2.5-flash",
}
_LLM_KEY_ENV = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}

_DOTENV_LOADED = False


class LLMError(Exception):
    """Any config / SDK / provider failure in the llm backend."""


def _load_dotenv():
    """Load a project's .env so provider keys are picked up, via python-dotenv.

    python-dotenv is imported lazily (like the SDKs); if it isn't installed we
    skip silently — keys can still come from the real environment. $BOT_ENV_FILE
    overrides the search; otherwise the nearest .env walking up from the cwd is
    used. Real environment variables always win (override=False). Runs once per
    process; call it from main() before resolving a provider.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    explicit = os.environ.get("BOT_ENV_FILE")
    if explicit:
        load_dotenv(explicit, override=False)
        return  # BOT_ENV_FILE overrides the search; don't also load a nearby .env
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)


def _llm_provider(explicit=None):
    if explicit:
        return explicit.lower()
    forced = os.environ.get("BOT_LLM_PROVIDER")
    if forced:
        return forced.strip().lower()
    for prov in _LLM_PROVIDERS:
        if any(os.environ.get(k) for k in _LLM_KEY_ENV[prov]):
            return prov
    return "anthropic"


def _llm_key(provider):
    for var in _LLM_KEY_ENV.get(provider, ()):
        if os.environ.get(var):
            return os.environ[var]
    return None


def _llm_model(provider, explicit=None):
    return (
        explicit
        or os.environ.get("BOT_LLM_MODEL")
        or os.environ.get(f"{provider.upper()}_MODEL")
        or _LLM_DEFAULT_MODEL.get(provider, "")
    )


def llm_available(provider=None):
    """True if a usable API key is configured for the resolved provider."""
    prov = _llm_provider(provider)
    return prov in _LLM_DEFAULT_MODEL and bool(_llm_key(prov))


def llm_missing_key_message(provider=None):
    """A helpful, actionable message for when no key is configured."""
    prov = _llm_provider(provider)
    var = _LLM_KEY_ENV.get(prov, ("ANTHROPIC_API_KEY",))[0]
    return (
        f"no API key for provider '{prov}'. set {var} (or switch providers with "
        f"--provider / BOT_LLM_PROVIDER, or set OPENAI_API_KEY / GEMINI_API_KEY)."
    )


def add_llm_args(parser, llm_flag=True):
    """Add the shared --llm / --provider / --model flags to an argparse parser."""
    if llm_flag:
        parser.add_argument(
            "--llm",
            action="store_true",
            help="use a model for the judgment instead of the offline heuristic",
        )
    parser.add_argument(
        "--provider",
        choices=_LLM_PROVIDERS,
        default=None,
        help="LLM provider (default: auto-detect from whichever API key is set)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="model id (default: the provider's default, or *_MODEL / BOT_LLM_MODEL)",
    )


def _llm_first_json(text):
    """Return the first balanced {...}/[...] substring of text, or None."""
    s = (text or "").strip()
    for fence in ("```json5", "```jsonc", "```json", "```", "~~~json", "~~~"):
        if s.startswith(fence):
            s = s[len(fence) :]
            if s.endswith("```") or s.endswith("~~~"):
                s = s[:-3]
            s = s.strip()
            break
    start = next((i for i, ch in enumerate(s) if ch in "{["), -1)
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def _llm_parse_json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    frag = _llm_first_json(text)
    if frag is not None:
        try:
            return json.loads(frag)
        except ValueError:
            pass
    raise LLMError(f"model did not return parseable JSON: {(text or '')[:200]!r}")


def _llm_schema_hint(prompt, schema):
    return (
        f"{prompt}\n\nRespond with ONLY a JSON value matching this JSON Schema, "
        f"no prose, no code fence:\n{json.dumps(schema)}"
    )


def _llm_anthropic(prompt, system, schema, model, max_tokens, temperature, base_url, key):
    try:
        import anthropic
    except ImportError as e:
        raise LLMError("anthropic SDK not installed — run: pip install anthropic") from e
    client = anthropic.Anthropic(api_key=key, **({"base_url": base_url} if base_url else {}))
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    if schema:
        kwargs["tools"] = [
            {"name": "emit", "description": "Emit the structured result.", "input_schema": schema}
        ]
        kwargs["tool_choice"] = {"type": "tool", "name": "emit"}
    try:
        resp = client.messages.create(**kwargs)
    except Exception as e:  # noqa: BLE001 — surface any SDK/network error uniformly
        raise LLMError(f"anthropic request failed: {e}") from e
    if schema:
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                return block.input
    text = "".join(
        getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text"
    )
    return _llm_parse_json(text) if schema else text


def _llm_openai(prompt, system, schema, model, max_tokens, temperature, base_url, key):
    try:
        from openai import OpenAI
    except ImportError as e:
        raise LLMError("openai SDK not installed — run: pip install openai") from e
    client = OpenAI(api_key=key, **({"base_url": base_url} if base_url else {}))
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    # Reasoning models (o1/o3/o4/gpt-5*) reject `max_tokens` and a non-default
    # temperature; they take `max_completion_tokens` and the default temperature.
    reasoning = (model or "").lower().startswith(("o1", "o3", "o4", "gpt-5"))
    kwargs = {
        "model": model,
        "messages": messages,
        "max_completion_tokens" if reasoning else "max_tokens": max_tokens,
    }
    if not reasoning:
        kwargs["temperature"] = temperature
    if schema:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "result", "schema": schema, "strict": True},
        }
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:  # noqa: BLE001
        if not schema:
            raise LLMError(f"openai request failed: {e}") from e
        # Endpoint may not support json_schema; retry with a prompt hint instead.
        kwargs.pop("response_format", None)
        kwargs["messages"] = messages[:-1] + [
            {"role": "user", "content": _llm_schema_hint(prompt, schema)}
        ]
        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as e2:  # noqa: BLE001
            raise LLMError(f"openai request failed: {e2}") from e2
    text = resp.choices[0].message.content
    return _llm_parse_json(text) if schema else text


def _llm_gemini(prompt, system, schema, model, max_tokens, temperature, base_url, key):
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise LLMError("google-genai SDK not installed — run: pip install google-genai") from e
    client_kwargs = {"api_key": key}
    if base_url:
        client_kwargs["http_options"] = types.HttpOptions(base_url=base_url)
    client = genai.Client(**client_kwargs)
    cfg = {"max_output_tokens": max_tokens, "temperature": temperature}
    if system:
        cfg["system_instruction"] = system
    contents = prompt
    if schema:
        cfg["response_mime_type"] = "application/json"
        contents = _llm_schema_hint(prompt, schema)
    try:
        resp = client.models.generate_content(
            model=model, contents=contents, config=types.GenerateContentConfig(**cfg)
        )
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"gemini request failed: {e}") from e
    text = resp.text or ""
    return _llm_parse_json(text) if schema else text


_LLM_DISPATCH = {"anthropic": _llm_anthropic, "openai": _llm_openai, "gemini": _llm_gemini}


def llm_complete(
    prompt,
    *,
    system=None,
    schema=None,
    provider=None,
    model=None,
    max_tokens=1024,
    temperature=0.0,
):
    """Send ``prompt`` to the resolved provider; return text, or a dict if schema.

    Raises :class:`LLMError` on missing key, missing SDK, network failure, or
    unparseable output — callers catch it and fall back to their offline path.
    """
    prov = _llm_provider(provider)
    fn = _LLM_DISPATCH.get(prov)
    if fn is None:
        raise LLMError(f"unknown provider {prov!r} — choose anthropic, openai, or gemini")
    key = _llm_key(prov)
    if not key:
        raise LLMError(llm_missing_key_message(prov))
    base_url = os.environ.get(f"{prov.upper()}_BASE_URL")
    return fn(
        prompt, system, schema, _llm_model(prov, model), max_tokens, temperature, base_url, key
    )


# --- end llm backend ------------------------------------------------------

# The interrogation. Each angle is an independent adversarial lens on the answer.
# `probe` is the boilerplate question grill asks under that angle in --dry-run;
# `instruction` is what it tells the model to do under that angle on a real run.
ANGLES: dict[str, dict[str, str]] = {
    "assumptions": {
        "probe": "What unstated assumptions does this answer rely on, and what happens if one is false?",
        "instruction": (
            "Surface the hidden assumptions this answer silently depends on. For "
            "the load-bearing one, ask a pointed question that exposes it and "
            "explain what breaks if the assumption does not hold."
        ),
    },
    "edge-cases": {
        "probe": "Which inputs, scales, or conditions does this answer quietly fail to cover?",
        "instruction": (
            "Find a concrete edge case, boundary, or scale the answer does not "
            "handle. Pose the question that drags it into the light and say why "
            "the answer is incomplete or wrong there."
        ),
    },
    "contradictions": {
        "probe": "Does the answer contradict itself or its own premises anywhere?",
        "instruction": (
            "Hunt for an internal contradiction or tension between claims in the "
            "answer. Quote the two parts that fight each other and ask which one "
            "the author actually means."
        ),
    },
    "sources": {
        "probe": "What's the source? Which claims are asserted but unsupported?",
        "instruction": (
            "Identify the strongest claim asserted without evidence. Ask 'what is "
            "the source?' for it and explain why it should not be taken on faith."
        ),
    },
    "overconfidence": {
        "probe": "Where is the answer more certain than the evidence warrants?",
        "instruction": (
            "Find where the answer is overconfident or miscalibrated — a hedge "
            "missing, a 'definitely' the evidence does not earn. Ask the question "
            "that forces it to state its actual confidence and why."
        ),
    },
    "falsifiability": {
        "probe": "What would change your mind? What evidence would prove this answer wrong?",
        "instruction": (
            "Ask what observation or evidence would make this answer wrong. If "
            "nothing could, say so — an unfalsifiable answer is a red flag, not a "
            "strong one."
        ),
    },
}

VERDICT_ORDER = ["holds", "weak", "shaky", "cracks"]

_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": VERDICT_ORDER},
        "angle": {"type": "string"},
        "question": {"type": "string"},
        "finding": {"type": "string"},
    },
    "required": ["verdict", "angle", "question", "finding"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a sharp, fair cross-examiner. You are given an ANSWER (and possibly "
    "the original QUESTION it responds to). Your job is to interrogate the answer "
    "from one specific angle: ask the single most penetrating follow-up question "
    "for that angle, then report what it reveals — whether the answer holds up, "
    "is weak, is shaky, or cracks outright under that questioning. Be adversarial "
    "but honest: if the answer genuinely survives this angle, say so (verdict "
    "'holds'). Do not manufacture flaws that aren't there — a clean result is a "
    "real result. Quote the answer where it helps."
)

_C = {
    "red": "\033[31m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "reset": "\033[0m",
}


def _c(name: str, s: str) -> str:
    return s if not sys.stdout.isatty() else f"{_C[name]}{s}{_C['reset']}"


_VERDICT_COLOR = {"cracks": "red", "shaky": "red", "weak": "yellow", "holds": "green"}


def interrogation_plan(angles: list[str]) -> list[dict[str, str]]:
    """Pure, offline: the questions grill would ask, grouped by angle.

    Returns a list of {"angle", "question"} dicts. No network, no SDK.
    """
    return [{"angle": a, "question": ANGLES[a]["probe"]} for a in angles]


def _run_one(answer: str, question: str, name: str, instruction: str, provider, model) -> dict:
    ctx = f"ORIGINAL QUESTION:\n{question}\n\n" if question.strip() else ""
    user = (
        f"{ctx}ANSWER UNDER EXAMINATION (between the markers):\n"
        f"<<<ANSWER\n{answer}\nANSWER>>>\n\n"
        f"Interrogation angle: {name}.\n{instruction}\n\n"
        f"Ask your single sharpest follow-up for this angle and report what it reveals."
    )
    # Cross-provider llm_complete returns the parsed dict directly. The tradeoff
    # for speaking Anthropic/OpenAI/Gemini alike is dropping Anthropic-only knobs
    # (adaptive `thinking`, `output_config` `effort`) — structured output is done
    # through each provider's native schema path.
    finding = llm_complete(
        user, system=_SYSTEM, schema=_SCHEMA, provider=provider, model=model, max_tokens=4000
    )
    finding["angle"] = name
    return finding


def _print_finding(f: dict) -> None:
    verdict = f.get("verdict", "holds")
    mark = "✗" if verdict in ("cracks", "shaky") else ("?" if verdict == "weak" else "✓")
    head = f"  {mark} {f['angle']:<15} [{verdict.upper()}]"
    print(_c(_VERDICT_COLOR.get(verdict, "dim"), _c("bold", head)))
    print(f"      {_c('cyan', 'asks:')}    {f.get('question', '')}")
    print(f"      {_c('dim', 'reveals:')} {f.get('finding', '')}")


def _verdict_idx(verdict: str) -> int:
    """Index into VERDICT_ORDER; an unknown verdict from a model sorts lowest."""
    return VERDICT_ORDER.index(verdict) if verdict in VERDICT_ORDER else 0


def _worst(findings: list[dict]) -> str:
    worst = "holds"
    for f in findings:
        v = f.get("verdict", "holds")
        if _verdict_idx(v) > _verdict_idx(worst):
            worst = v
    return worst


def run(answer: str, question: str, angles: list[str], provider=None, model=None) -> int:
    if not llm_available(provider):
        print(_c("red", llm_missing_key_message(provider)), file=sys.stderr)
        print(_c("dim", "(or use --dry-run)"), file=sys.stderr)
        return 2

    print(
        _c(
            "bold",
            f"\ngrill is putting the answer in the hot seat "
            f"({len(angles)} angles, model={model or 'provider default'})…\n",
        )
    )

    findings: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(angles)) as ex:
        futs = {
            ex.submit(_run_one, answer, question, n, ANGLES[n]["instruction"], provider, model): n
            for n in angles
        }
        for fut in concurrent.futures.as_completed(futs):
            name = futs[fut]
            try:
                findings.append(fut.result())
            except Exception as e:  # noqa: BLE001
                print(_c("red", f"  ! {name} angle errored: {e}"), file=sys.stderr)

    findings.sort(key=lambda f: _verdict_idx(f.get("verdict", "holds")), reverse=True)
    print(_c("bold", "── cross-examination " + "─" * 51))
    for f in findings:
        _print_finding(f)

    worst = _worst(findings)
    cracked = sum(1 for f in findings if f.get("verdict") in ("shaky", "cracks"))
    print()
    verdict = f"{cracked}/{len(findings)} angles cracked it. worst: {worst.upper()}"
    print(_c(_VERDICT_COLOR.get(worst, "green"), _c("bold", "verdict: " + verdict)))

    # CI-friendly: fail if the answer cracked or went shaky anywhere.
    return 1 if _verdict_idx(worst) >= _verdict_idx("shaky") else 0


def dry_run(angles: list[str], question: str = "") -> int:
    print(_c("bold", "\ngrill interrogation plan (dry run — no API call):\n"))
    if question.strip():
        print(_c("dim", f"  re: {question.strip()}\n"))
    for item in interrogation_plan(angles):
        print(_c("cyan", f"  {item['angle']}"))
        print(f"    {item['question']}\n")
    print(
        _c(
            "dim",
            "set an API key (ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY) "
            "and drop --dry-run to actually grill it.\n",
        )
    )
    return 0


def main(argv=None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(
        prog="grill",
        description="put it in the hot seat.",
    )
    p.add_argument("file", nargs="?", help="answer file to interrogate (default: stdin)")
    p.add_argument(
        "--question", default="", help="the original question / context the answer responds to"
    )
    p.add_argument(
        "--angles",
        default=",".join(ANGLES),
        help=f"comma-separated subset of: {', '.join(ANGLES)}",
    )
    add_llm_args(p, llm_flag=False)  # adds --provider and --model
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the interrogation plan without calling the API",
    )
    args = p.parse_args(argv)

    angles = [a.strip() for a in args.angles.split(",") if a.strip()]
    bad = [a for a in angles if a not in ANGLES]
    if bad:
        print(f"unknown angle(s): {', '.join(bad)}", file=sys.stderr)
        print(f"choose from: {', '.join(ANGLES)}", file=sys.stderr)
        return 2
    if not angles:
        print("no angles selected (--angles was empty).", file=sys.stderr)
        print(f"choose from: {', '.join(ANGLES)}", file=sys.stderr)
        return 2

    if args.dry_run:
        return dry_run(angles, args.question)

    if args.file:
        answer = open(args.file, encoding="utf-8").read()
    else:
        if sys.stdin.isatty():
            print(
                "no answer given. pass a file or pipe one in. (--dry-run to just see the plan)",
                file=sys.stderr,
            )
            return 2
        answer = sys.stdin.read()

    if not answer.strip():
        print("empty answer.", file=sys.stderr)
        return 2

    return run(answer, args.question, angles, args.provider, args.model)


if __name__ == "__main__":
    raise SystemExit(main())
