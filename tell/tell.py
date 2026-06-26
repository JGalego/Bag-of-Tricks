#!/usr/bin/env python3
"""tell — every AI has a tell.

Reads a passage and scores how "AI-written" it reads, listing the specific
tells it found (overused words, cliché phrases, em-dash overuse, emoji, …).
It does not rewrite — it diagnoses. deadpan prevents tells at generation;
tell finds them after.

    echo "Let's delve into this rich tapestry — it's a testament." | tell.py
    -> score 90/100, hits: delve, tapestry, testament, em-dash …

    tell.py --json draft.md
    tell.py --max 30 draft.md   # exit 1 in CI if the prose reads too AI
    tell.py --llm draft.md      # ask a model to rate the slop it can read

Custom patterns
---------------
The offline lexical mode (everything except ``--llm``) starts from the built-in
lexicon and can be extended with your own tells. Pass ``--patterns FILE``
(repeatable) or set ``TELL_PATTERNS`` to an os.pathsep-separated list of files.
Each file is JSON of the shape::

    {
      "words": ["synergize", "thought leader"],
      "phrases": [
        ["needle-mover", "\\bneedle[- ]mover\\b"],
        ["circle back", "\\bcircle back\\b"]
      ]
    }

``words`` are matched case-insensitively on word boundaries (spaces allowed for
multiword terms); ``phrases`` are ``[label, regex]`` pairs. User entries extend
the built-ins; they do not replace them. Custom patterns do NOT affect ``--llm``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
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
    for fence in ("```json", "```json5", "```jsonc", "```", "~~~json", "~~~"):
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

# --- tell lexicon ---------------------------------------------------------
# Edit these freely. Word lists are matched case-insensitively on word
# boundaries; phrases are regexes; structural tells are counted separately.

# Single words that pattern-match LLM prose. Word-boundary, case-insensitive.
OVERUSED_WORDS = [
    "delve",
    "tapestry",
    "testament",
    "realm",
    "navigate",
    "underscore",
    "leverage",
    "robust",
    "seamless",
    "crucial",
    "pivotal",
    "multifaceted",
    "nuanced",
    "intricate",
    "bustling",
    "vibrant",
    "foster",
    "harness",
    "elevate",
    "unlock",
    "embark",
    "landscape",
    "beacon",
    "treasure trove",
]

# Cliché phrases / constructions. Each entry is (label, regex).
CLICHE_PHRASES = [
    ("it's not just X, it's Y", r"\bit'?s not just\b[^.!?\n]*?,?\s*it'?s\b"),
    ("not only … but also", r"\bnot only\b[^.!?\n]*?\bbut also\b"),
    ("in conclusion", r"\bin conclusion\b"),
    ("in summary", r"\bin summary\b"),
    ("it's worth noting", r"\bit'?s worth noting\b"),
    ("in today's fast-paced world", r"\bin today'?s fast[- ]paced world\b"),
    ("when it comes to", r"\bwhen it comes to\b"),
    ("a testament to", r"\ba testament to\b"),
    ("plays a crucial role", r"\bplays? a (?:crucial|pivotal|vital|key) role\b"),
    ("at the end of the day", r"\bat the end of the day\b"),
    ("the world of", r"\bthe world of\b"),
    ("dive into", r"\bdive into\b"),
    ("rich tapestry", r"\brich tapestry\b"),
    ("ever-evolving", r"\bever[- ]evolving\b"),
    ("game-changer", r"\bgame[- ]changer\b"),
]

# Emoji + decorative symbols (same range used by deadpan).
_EMOJI = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f0ff"
    "\U00002190-\U000021ff\U00002b00-\U00002bff\U0000fe0f\U0000200d]+"
)

# Rule-of-three: "a, b, and c" — three comma-separated items capped by "and"/"or".
_RULE_OF_THREE = re.compile(r"\b[\w'-]+,\s+[\w'-]+,\s+(?:and|or)\s+[\w'-]+\b", re.IGNORECASE)

# Bold runs: **like this** (markdown emphasis).
_BOLD_RUN = re.compile(r"\*\*[^*\n]+\*\*")


# --- custom patterns ------------------------------------------------------
# Built-ins are the base; user files extend (never replace) them. See the module
# docstring for the JSON shape. These mutate the module-level lexicon in place so
# the existing offline `tell()` picks them up with no signature change.


def merge_patterns(spec: dict) -> None:
    """Merge one parsed ``{"words": [...], "phrases": [[label, regex], ...]}``
    spec into the built-in lexicon, skipping duplicates and malformed entries."""
    seen_words = {w.lower() for w in OVERUSED_WORDS}
    for word in spec.get("words", []) or []:
        if isinstance(word, str) and word.strip() and word.lower() not in seen_words:
            OVERUSED_WORDS.append(word)
            seen_words.add(word.lower())

    seen_phrases = {label for label, _ in CLICHE_PHRASES}
    for entry in spec.get("phrases", []) or []:
        if not (isinstance(entry, (list, tuple)) and len(entry) == 2):
            continue
        label, pat = entry
        if not (isinstance(label, str) and isinstance(pat, str)):
            continue
        re.compile(pat)  # validate eagerly so a bad regex fails loud, not silent
        if label not in seen_phrases:
            CLICHE_PHRASES.append((label, pat))
            seen_phrases.add(label)


def load_patterns(paths: list[str]) -> None:
    """Load and merge each JSON pattern file in ``paths`` (in order)."""
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            merge_patterns(json.load(fh))


def _count_words(text: str) -> int:
    return max(1, len(re.findall(r"\b\w+\b", text)))


def _word_hits(text: str) -> list[dict]:
    hits = []
    for word in OVERUSED_WORDS:
        # word-boundary, case-insensitive; allow space inside multiword terms.
        rx = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
        n = len(rx.findall(text))
        if n:
            hits.append({"category": "overused word", "tell": word, "count": n})
    return hits


def _phrase_hits(text: str) -> list[dict]:
    hits = []
    for label, pat in CLICHE_PHRASES:
        n = len(re.findall(pat, text, re.IGNORECASE))
        if n:
            hits.append({"category": "cliché phrase", "tell": label, "count": n})
    return hits


def _structural_hits(text: str) -> list[dict]:
    hits = []
    em = text.count("—")
    if em:
        hits.append({"category": "structural", "tell": "em-dash", "count": em})
    emoji = sum(len(m.group(0)) for m in _EMOJI.finditer(text))
    if emoji:
        hits.append({"category": "structural", "tell": "emoji", "count": emoji})
    three = len(_RULE_OF_THREE.findall(text))
    if three:
        hits.append({"category": "structural", "tell": "rule-of-three list", "count": three})
    bold = len(_BOLD_RUN.findall(text))
    if bold:
        hits.append({"category": "structural", "tell": "bold run", "count": bold})
    return hits


def tell(text: str) -> dict:
    """Diagnose how 'AI-written' ``text`` reads.

    Returns ``{"score": 0-100, "hits": [...], "total": int}`` where each hit is
    ``{"category", "tell", "count"}``.

    Score formula (deterministic, monotonic in total tells):
        density = total_tells / words * 100      # tells per 100 words
        score   = round(100 * (1 - exp(-density / 6)))
    Saturating so it stays in 0-100; more tells never lowers the score for a
    fixed word count. ~6 tells/100 words lands around 63; it climbs from there.
    """
    hits = _word_hits(text) + _phrase_hits(text) + _structural_hits(text)
    total = sum(h["count"] for h in hits)
    words = _count_words(text)

    density = total / words * 100.0
    # 1 - exp(-x) is monotonic increasing, bounded in [0, 1).
    score = round(100 * (1 - math.exp(-density / 6.0)))
    score = max(0, min(100, score))

    # Sort hits: highest count first, then category, then tell — stable report.
    hits.sort(key=lambda h: (-h["count"], h["category"], h["tell"]))
    return {"score": score, "hits": hits, "total": total}


# --- model-backed scoring (opt-in) ----------------------------------------
# The lexicon above is fast, deterministic, and zero-dependency, but it only
# catches the exact words and shapes it was told about. `--llm` asks a model to
# read the passage and rate how AI-written it reads — catching paraphrased slop
# and structural blandness the lexicon misses, and naming the specific tells.

_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "hits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["overused word", "cliché phrase", "structural"],
                    },
                    "tell": {"type": "string"},
                    "count": {"type": "integer"},
                },
                "required": ["category", "tell", "count"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["score", "hits"],
    "additionalProperties": False,
}

_LLM_SYSTEM = (
    "You are an expert at spotting AI-generated prose. Read the passage and rate "
    "how AI-written it reads on a 0-100 scale (0 = unmistakably human, 100 = "
    "unmistakably machine). Catch the slop a keyword list misses: paraphrased "
    "filler, hollow even-handedness, mechanical structure, and rhythm — not just "
    "stock words. Then list the SPECIFIC tells you found with a count for each, "
    'tagging every tell with a category of exactly "overused word", "cliché '
    'phrase", or "structural". Be specific: name the actual word or construction, '
    "not a vague description. Clean, plain, idiosyncratic human prose must score "
    "low — do not invent tells that are not there."
)


def tell_llm(text: str, provider: str | None = None, model: str | None = None) -> dict:
    """Model-backed tell scoring — reads the passage the way a human would.

    Same return shape as :func:`tell`: ``{"score": 0-100, "hits": [...],
    "total": int}`` with each hit ``{"category", "tell", "count"}``. ``total`` is
    the sum of hit counts (computed here if the model omits it). Raises
    ``LLMError`` on provider failure so the caller can exit cleanly.
    """
    prompt = f"Rate how AI-written this passage reads and list its tells:\n\n{text}"
    data = llm_complete(
        prompt, system=_LLM_SYSTEM, schema=_LLM_SCHEMA, provider=provider, model=model
    )

    hits: list[dict] = []
    for item in data.get("hits", []) or []:
        try:
            count = int(item.get("count", 1))
        except (TypeError, ValueError):
            count = 1
        hits.append(
            {
                "category": str(item.get("category", "structural")),
                "tell": str(item.get("tell", "")),
                "count": max(1, count),
            }
        )

    total = data.get("total")
    if not isinstance(total, int):
        total = sum(h["count"] for h in hits)

    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))

    hits.sort(key=lambda h: (-h["count"], h["category"], h["tell"]))
    return {"score": score, "hits": hits, "total": total}


def _report(result: dict) -> str:
    lines = [f"score {result['score']}/100  ({result['total']} tells)"]
    by_cat: dict[str, list[dict]] = {}
    for h in result["hits"]:
        by_cat.setdefault(h["category"], []).append(h)
    if not result["hits"]:
        lines.append("  no tells found — reads clean.")
    for cat in ("overused word", "cliché phrase", "structural"):
        items = by_cat.get(cat)
        if not items:
            continue
        lines.append(f"\n{cat}s:")
        for h in items:
            lines.append(f"  {h['tell']} ×{h['count']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(prog="tell", description="every AI has a tell.")
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument("--score", action="store_true", help="print just the integer score")
    p.add_argument("--json", action="store_true", help="emit the result dict as JSON")
    p.add_argument(
        "--max",
        type=int,
        default=None,
        metavar="N",
        help="exit 1 if score > N (gate prose in CI)",
    )
    p.add_argument(
        "--patterns",
        action="append",
        default=[],
        metavar="FILE",
        help="JSON file of extra tells to merge into the lexicon (repeatable); "
        "honors $TELL_PATTERNS (os.pathsep-separated) as a fallback. Offline mode only.",
    )
    add_llm_args(p)
    args = p.parse_args(argv)

    # Custom patterns extend the offline lexicon. --patterns wins; otherwise fall
    # back to $TELL_PATTERNS. (No effect on --llm, which reads the raw passage.)
    pattern_files = list(args.patterns)
    if not pattern_files and os.environ.get("TELL_PATTERNS"):
        pattern_files = [p for p in os.environ["TELL_PATTERNS"].split(os.pathsep) if p]
    if pattern_files:
        try:
            load_patterns(pattern_files)
        except (OSError, ValueError, re.error) as e:
            sys.stderr.write(f"[tell] could not load patterns: {e}\n")
            return 2

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    if args.llm:
        try:
            result = tell_llm(raw, provider=args.provider, model=args.model)
        except LLMError as e:
            sys.stderr.write(f"[tell] llm mode failed: {e}\n")
            return 2
    else:
        result = tell(raw)

    if args.json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    elif args.score:
        sys.stdout.write(f"{result['score']}\n")
    else:
        sys.stdout.write(_report(result))

    if args.max is not None and result["score"] > args.max:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
