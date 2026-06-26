#!/usr/bin/env python3
"""lineup — same prompt, the whole lineup. see who did it.

Run one prompt across several models and lay the answers side by side so you can
pick the best one (or spot the odd one out). Great for model selection and for
seeing where models disagree — a quick parade you walk past, not a benchmark you
run overnight.

The lineup is multi-provider: each model id routes to the right backend by its
prefix (claude*/anthropic* -> Anthropic, gpt*/o1*/o3*/chatgpt* -> OpenAI,
gemini*/models/gemini* -> Gemini), or you can be explicit with a
"provider:model" id (e.g. "openai:gpt-4o"). A real run just needs the matching
key set (ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY) and that
provider's SDK (pip install anthropic / openai / google-genai).

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...   # and/or OPENAI_API_KEY / GEMINI_API_KEY
    python3 lineup.py --prompt "Explain TCP in one sentence."
    cat prompt.txt | python3 lineup.py
    python3 lineup.py prompt.txt --models claude-opus-4-8,gpt-4o,gemini-2.5-flash
    python3 lineup.py prompt.txt --models "openai:gpt-4o,anthropic:claude-haiku-4-5"
    python3 lineup.py prompt.txt --judge claude-opus-4-8
    python3 lineup.py --prompt "..." --dry-run     # no API key needed
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

# The default lineup: an opus + a sonnet + a haiku tier, mirroring the model
# family strawman uses. Same prompt to each; pick the best or spot the outlier.
DEFAULT_MODELS = [
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]

MAX_TOKENS = 1024

_C = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "reset": "\033[0m",
}


def _c(name: str, s: str) -> str:
    return s if not sys.stdout.isatty() else f"{_C[name]}{s}{_C['reset']}"


def parse_models(raw: str) -> list[str]:
    """Split a comma-separated --models string into a clean list of model ids."""
    return [m.strip() for m in raw.split(",") if m.strip()]


def plan(prompt: str, models: list[str]) -> str:
    """Pure function: render the lineup PLAN — which prompt goes to which models."""
    preview = prompt.strip()
    if len(preview) > 280:
        preview = preview[:277] + "..."
    lines = [
        f"lineup plan — 1 prompt, {len(models)} model(s) in the parade:",
        "",
        "prompt:",
    ]
    lines += [f"  | {line}" for line in preview.splitlines() or [""]]
    lines.append("")
    lines.append("would be sent — verbatim — to each of:")
    for m in models:
        lines.append(f"  • {m}")
    return "\n".join(lines)


def provider_for(model_id: str, default: str | None = None) -> tuple[str | None, str]:
    """Resolve a model id to (provider, model).

    A "provider:model" id (e.g. "openai:gpt-4o") splits explicitly. Otherwise
    the provider is inferred from the id's prefix; if nothing matches, ``default``
    is used (which may be None to let the helper auto-detect).
    """
    if ":" in model_id:
        prov, real = model_id.split(":", 1)
        prov = prov.strip().lower()
        if prov in _LLM_PROVIDERS:
            return prov, real.strip()
    low = model_id.lower()
    if low.startswith(("claude", "anthropic")):
        return "anthropic", model_id
    if low.startswith(("gpt", "o1", "o3", "chatgpt")):
        return "openai", model_id
    if low.startswith(("gemini", "models/gemini")):
        return "gemini", model_id
    return default, model_id


def _call_one(model: str, prompt: str, default_provider: str | None) -> dict:
    prov, real_model = provider_for(model, default_provider)
    text = llm_complete(prompt, provider=prov, model=real_model, max_tokens=MAX_TOKENS)
    return {"model": model, "text": text}


def _judge(model: str, prompt: str, answers: list[dict], default_provider: str | None) -> str:
    roster = "\n\n".join(f"[{a['model']}]\n{a['text']}" for a in answers if not a.get("error"))
    user = (
        f"ORIGINAL PROMPT:\n{prompt}\n\n"
        f"Here are answers from different models to that prompt:\n\n{roster}\n\n"
        f"Pick the single best answer. Name the model id you picked and explain "
        f"in 2-3 sentences why it beats the others. Be specific and honest."
    )
    prov, real_model = provider_for(model, default_provider)
    return llm_complete(user, provider=prov, model=real_model, max_tokens=MAX_TOKENS)


def _print_answer(a: dict) -> None:
    head = f"── {a['model']} "
    head = head + "─" * max(0, 72 - len(head))
    print(_c("bold", _c("cyan", head)))
    if a.get("error"):
        print(_c("red", f"  ! errored: {a['error']}"))
    else:
        body = a["text"].strip() or _c("dim", "(empty response)")
        print(body)
    print()


def run(
    prompt: str,
    models: list[str],
    judge: str | None = None,
    provider: str | None = None,
) -> int:
    # Each model call routes to its own provider and may fail independently;
    # those failures are caught per-future below, so there's nothing to set up.
    print(_c("bold", f"\nlineup running — same prompt across {len(models)} model(s)…\n"))

    answers: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(models)) as ex:
        futs = {ex.submit(_call_one, m, prompt, provider): m for m in models}
        for fut in concurrent.futures.as_completed(futs):
            model = futs[fut]
            try:
                answers.append(fut.result())
            except Exception as e:  # noqa: BLE001
                answers.append({"model": model, "error": str(e)})

    # Keep the lineup in the order the user listed the models.
    order = {m: i for i, m in enumerate(models)}
    answers.sort(key=lambda a: order.get(a["model"], len(models)))

    for a in answers:
        _print_answer(a)

    errored = sum(1 for a in answers if a.get("error"))
    print(_c("dim", f"{len(answers) - errored}/{len(answers)} answered."))

    if judge:
        live = [a for a in answers if not a.get("error")]
        if len(live) < 2:
            print(_c("yellow", "\nnot enough answers to judge (need at least 2)."))
        else:
            print(_c("bold", f"\n── verdict (judge: {judge}) " + "─" * 40))
            try:
                print(_judge(judge, prompt, answers, provider))
            except Exception as e:  # noqa: BLE001
                print(_c("red", f"judge errored: {e}"), file=sys.stderr)

    # Non-zero only if every model in the lineup failed.
    return 1 if errored == len(answers) else 0


def dry_run(prompt: str, models: list[str]) -> int:
    print(_c("bold", "\nlineup (dry run — no API call):\n"))
    print(plan(prompt, models))
    print()
    print(
        _c(
            "dim",
            "set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY and drop "
            "--dry-run to actually run the lineup.\n",
        )
    )
    return 0


def main(argv=None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(
        prog="lineup",
        description="same prompt, the whole lineup. see who did it.",
    )
    p.add_argument("file", nargs="?", help="prompt file (default: --prompt or stdin)")
    p.add_argument("--prompt", help="the prompt to put in front of the lineup")
    p.add_argument(
        "--models",
        default=",".join(DEFAULT_MODELS),
        help=f"comma-separated model ids (default: {', '.join(DEFAULT_MODELS)})",
    )
    p.add_argument(
        "--judge",
        metavar="MODEL",
        help="after collecting answers, ask this model to pick the best and say why",
    )
    p.add_argument(
        "--provider",
        choices=_LLM_PROVIDERS,
        default=None,
        help="default provider for model ids that don't name one (default: auto-detect)",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="print the lineup plan without calling the API"
    )
    args = p.parse_args(argv)

    models = parse_models(args.models)
    if not models:
        print("no models given — pass --models a,b,c", file=sys.stderr)
        return 2

    # Resolve the prompt: --prompt wins, then a file arg, then stdin.
    if args.prompt is not None:
        prompt = args.prompt
    elif args.file:
        prompt = open(args.file, encoding="utf-8").read()
    elif not sys.stdin.isatty():
        prompt = sys.stdin.read()
    else:
        print(
            "no prompt given. use --prompt, pass a file, or pipe one in. "
            "(--dry-run to just see the plan)",
            file=sys.stderr,
        )
        return 2

    if not prompt.strip():
        print("empty prompt.", file=sys.stderr)
        return 2

    if args.dry_run:
        return dry_run(prompt, models)

    return run(prompt, models, judge=args.judge, provider=args.provider)


if __name__ == "__main__":
    raise SystemExit(main())
