#!/usr/bin/env python3
"""interrobang ‽ — make it ask before it acts.

The default LLM reflex is to be helpful by answering immediately — which means
guessing when a request is underspecified. interrobang flips that: when the
ask is ambiguous, fire ONE sharp clarifying question first.

Two modes, zero dependencies:

    interrobang.py prompt
        Print the system-prompt addendum that installs the reflex flip.
        Prepend it to your agent's system prompt.

    interrobang.py check transcript.txt
        Lint an assistant response (or transcript) for places it likely
        GUESSED instead of asking — "I'll assume…", "presumably…",
        "I'll go with…". Heuristic, fast, catches the obvious ones.

        --patterns FILE     add your own guess-phrase regexes (repeatable).
                            FILE is JSON: {"patterns": ["<regex>", ...]}
                            Each pattern is merged into the built-ins and
                            compiled case-insensitively. The env var
                            INTERROBANG_PATTERNS (os.pathsep-separated paths)
                            is honored as a fallback.

        --llm               read the transcript with a model instead of regex,
                            catching semantic guesses the patterns miss (e.g.
                            silently picking a default without flagging it).

The glyph is ‽ (U+203D, the interrobang). That's the whole brand.
"""

from __future__ import annotations

import argparse
import json
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

GLYPH = "‽"  # ‽

ADDENDUM = """\
## Ask before you act ‽

When a request is underspecified in a way that changes what you would do,
ask ONE sharp clarifying question before acting — do not guess.

- A choice changes the outcome and you can't infer it from context → ask.
- The request is missing a fact you need and can't safely default → ask.
- The action is hard to reverse (deletes, sends, deploys, spends) and the
  scope is unclear → ask.

But do NOT ask when:
- The answer is obvious from context, the codebase, or convention.
- There's a sane default and the cost of guessing wrong is low → pick the
  default, state it in one line, and proceed.
- You'd be asking just to confirm something the user already made clear.

Ask exactly ONE question — the one whose answer unblocks the most. Make it
specific and answerable in a sentence; offer the likely options if you can.
Then stop and wait. One sharp question beats five paragraphs of assumptions.
"""

# Phrases that usually mean "I guessed instead of asking."
_GUESS_PATTERNS = [
    r"\bi'?ll assume\b",
    r"\bi'?ll go with\b",
    r"\bi'?ll just\b",
    r"\bassuming (?:that |you )",
    r"\bi'?m assuming\b",
    r"\bpresumably\b",
    r"\bi'?ll take it that\b",
    r"\bi'?ll interpret (?:this|that|it) as\b",
    r"\blikely you (?:mean|want)\b",
    r"\bi'?ll guess\b",
    r"\bdefaulting to\b",
    r"\bif (?:i|we) had to guess\b",
    r"\bi'?ll proceed (?:as if|assuming)\b",
]
_GUESS_RE = [re.compile(p, re.IGNORECASE) for p in _GUESS_PATTERNS]

_C = {
    "yellow": "\033[33m",
    "green": "\033[32m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def _c(name: str, s: str) -> str:
    return s if not sys.stdout.isatty() else f"{_C[name]}{s}{_C['reset']}"


def _load_patterns(files: list[str] | None) -> list[re.Pattern]:
    """Compile the built-in guess patterns plus any custom ones from JSON files.

    Each FILE is JSON shaped ``{"patterns": ["<regex>", ...]}``; every regex is
    MERGED into the built-ins and compiled case-insensitively. When ``files`` is
    empty, the env var ``INTERROBANG_PATTERNS`` (os.pathsep-separated paths) is
    used as a fallback. Built-ins always come first.
    """
    paths = list(files or [])
    if not paths:
        env = os.environ.get("INTERROBANG_PATTERNS", "")
        paths = [p for p in env.split(os.pathsep) if p]
    if not paths:
        return list(_GUESS_RE)

    compiled = list(_GUESS_RE)
    for path in paths:
        data = json.loads(open(path, encoding="utf-8").read())
        for pat in data.get("patterns", []):
            compiled.append(re.compile(pat, re.IGNORECASE))
    return compiled


def lint(text: str, patterns: list[re.Pattern] | None = None) -> list[tuple[int, str, str]]:
    """Return (line_no, matched_phrase, line) for likely guesses.

    ``patterns`` defaults to the built-in guess regexes; pass a merged list
    (see :func:`_load_patterns`) to add your own.
    """
    rules = patterns if patterns is not None else _GUESS_RE
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        for rx in rules:
            m = rx.search(line)
            if m:
                hits.append((i, m.group(0), line.strip()))
                break
    return hits


# --- model-backed lint (opt-in) -------------------------------------------
# The regex lint above is fast and deterministic, but blind to guesses that
# don't wear an obvious phrase — silently picking a default, quietly resolving
# an ambiguity, answering a question the user never fully specified. `--llm`
# reads the transcript with a model and flags those semantic cases too.

_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "guesses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "phrase": {"type": "string"},
                    "snippet": {"type": "string"},
                },
                "required": ["line", "phrase", "snippet"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["guesses"],
    "additionalProperties": False,
}

_LLM_SYSTEM = (
    "You audit an assistant transcript for places it GUESSED or silently "
    "ASSUMED instead of asking ONE sharp clarifying question. Flag every spot "
    "where the request was underspecified in a way that changes the outcome and "
    "the assistant resolved it without asking — including cases with no tell-tale "
    "phrase: silently picking a default, quietly choosing between readings, "
    "answering a question the user never pinned down. Do NOT flag genuine "
    "clarifying questions, or sane defaults the assistant explicitly stated. The "
    "input is numbered '<line>: <text>'. For each guess return the 1-based line "
    "number, the exact phrase (a short substring of that line that betrays the "
    "guess), and the line's text as the snippet. Return an empty list if it asked "
    "or never needed to."
)


def lint_llm(
    text: str,
    provider: str | None = None,
    model: str | None = None,
) -> list[tuple[int, str, str]]:
    """Model-backed lint — same shape as :func:`lint`, semantic instead of regex.

    Returns ``(line_no, matched_phrase, line)`` tuples for places the assistant
    guessed instead of asking, including cases the regex patterns miss. Raises
    ``LLMError`` on provider failure so the caller can exit cleanly.
    """
    lines = text.splitlines()
    if not lines:
        return []
    numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(lines, 1))
    prompt = (
        "Audit this transcript for guesses-instead-of-questions ‽\n\n"
        f"{numbered}\n\nReturn every line where it guessed instead of asking."
    )
    data = llm_complete(
        prompt, system=_LLM_SYSTEM, schema=_LLM_SCHEMA, provider=provider, model=model
    )
    hits: list[tuple[int, str, str]] = []
    for item in data.get("guesses", []):
        line_no = int(item.get("line", 0))
        phrase = item.get("phrase", "")
        # Fall back to the phrase (text), not item["line"] (a line number).
        snippet = item.get("snippet") or phrase
        hits.append((line_no, phrase, str(snippet).strip()))
    return hits


def cmd_prompt() -> int:
    sys.stdout.write(ADDENDUM)
    return 0


def cmd_check(
    path: str | None,
    *,
    llm: bool = False,
    provider: str | None = None,
    model: str | None = None,
    patterns: list[str] | None = None,
) -> int:
    if path:
        try:
            text = open(path, encoding="utf-8").read()
        except OSError as e:
            print(f"{GLYPH} cannot read {path}: {e}", file=sys.stderr)
            return 2
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        print("nothing to check. pass a file or pipe text in.", file=sys.stderr)
        return 2

    if llm:
        try:
            hits = lint_llm(text, provider=provider, model=model)
        except LLMError as e:
            print(f"{GLYPH} llm mode failed: {e}", file=sys.stderr)
            return 2
    else:
        hits = lint(text, patterns=_load_patterns(patterns))
    asked = text.count("?")
    if not hits:
        print(
            _c("green", f"{GLYPH} no obvious guesses found ({asked} question mark(s) in the text).")
        )
        return 0

    print(
        _c(
            "bold",
            _c("yellow", f"{GLYPH} {len(hits)} likely guess(es) — should it have asked instead?\n"),
        )
    )
    for line_no, phrase, line in hits:
        print(f"  {_c('dim', f'L{line_no}')}  …{_c('yellow', phrase)}…")
        print(f"        {line}")
    print(_c("dim", f"\n({asked} question mark(s) total — did it ask, or just assume?)"))
    # non-zero so it can gate a review
    return 1


def main(argv=None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(
        prog="interrobang",
        description="make it ask before it acts. ‽",
    )
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("prompt", help="print the system-prompt addendum")
    c = sub.add_parser("check", help="lint text for guesses-instead-of-questions")
    c.add_argument("file", nargs="?", help="file to check (default: stdin)")
    c.add_argument(
        "--patterns",
        action="append",
        metavar="FILE",
        help='JSON {"patterns": ["<regex>", ...]} merged into the built-ins '
        "(repeatable; env INTERROBANG_PATTERNS is the fallback)",
    )
    add_llm_args(c)
    args = p.parse_args(argv)

    if args.cmd == "prompt":
        return cmd_prompt()
    if args.cmd == "check":
        return cmd_check(
            args.file,
            llm=args.llm,
            provider=args.provider,
            model=args.model,
            patterns=args.patterns,
        )
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
