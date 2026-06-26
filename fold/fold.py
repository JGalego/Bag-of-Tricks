#!/usr/bin/env python3
"""fold — know when to fold.

In poker you fold a weak hand instead of bluffing it. ``fold`` is the honest
counterpart to ``bluff``: it catches *overconfident* language — a draft answer
asserting with false certainty where it should hedge or abstain. A stdin->stdout
filter: it tags each overconfidence marker like ``[FOLD:certainty]`` so the
draft can be softened, and writes a summary to stderr. It flags *tone*, not
truth — it tells you where you're bluffing, not whether you're wrong.

    echo "This will definitely always work, guaranteed." | fold.py
    -> This will [FOLD:certainty] [FOLD:absolute] work, [FOLD:no_doubt].

    cat answer.txt | fold.py --check     # exit 1 if it overclaims anywhere
    fold.py --report < answer.txt        # list the tells with offsets
    fold.py --llm < answer.txt           # let a model judge unearned confidence
    fold.py --patterns extra.json        # add custom detectors (offline mode)

Custom detectors (offline mode only — not --llm) load from a JSON file shaped:

    {"detectors": {"<type-name>": "<regex>"}}

Each regex is compiled case-insensitively and MERGED into the built-ins; a user
entry with a built-in's name overrides it. Pass --patterns FILE (repeatable) or
set FOLD_PATTERNS to an os.pathsep-separated list of files as a fallback.
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

# --- detectors ------------------------------------------------------------
# Each entry maps a marker type to a compiled regex. Spans are collected across
# all of them and resolved left-to-right so overlapping matches never corrupt
# offsets. Patterns lean toward high-signal certainty/bluff phrasing — we flag
# overclaiming tone, not facts, so we'd rather miss a soft one than nag every
# ordinary word. All matching is case-insensitive.

_DETECTORS: dict[str, re.Pattern[str]] = {
    # Bare certainty adverbs — the model swearing it's sure.
    "certainty": re.compile(
        r"\b(?:certainly|definitely|undoubtedly|indisputably|unquestionably|"
        r"obviously|clearly|surely|absolutely|positively)\b",
        re.IGNORECASE,
    ),
    # Doubt-erasing constructions — "without a doubt", "100%", "guaranteed".
    "no_doubt": re.compile(
        # "100%" lives in its own branch: a trailing \b after "%" (a non-word
        # char) never matches in normal text, so it can't ride the shared \b.
        r"\b(?:without(?: a)? doubt|beyond(?: any)? doubt|"
        r"there is no question|no doubt about it|guaranteed)\b|\b100\s*%",
        re.IGNORECASE,
    ),
    # Sweeping absolutes. These are common words, so we only fire on the
    # universal quantifiers themselves — "always/never/every/all" — which is
    # where unearned certainty hides. ("all" is included; tune --only if noisy.)
    "absolute": re.compile(
        r"\b(?:always|never|every|all|none|everything|nothing|"
        r"everyone|nobody|impossible)\b",
        re.IGNORECASE,
    ),
    # Trust-me / appeal-to-consensus authority — confidence borrowed, not earned.
    "false_authority": re.compile(
        r"\b(?:trust me|everyone knows|everybody knows|"
        r"it(?:'s| is) (?:well[- ])?known|as everyone knows|"
        r"needless to say|it goes without saying)\b",
        re.IGNORECASE,
    ),
}

_ALL_TYPES = frozenset(_DETECTORS)

# How much of a marker to echo in a preview before the ellipsis.
_PREVIEW = 24


def _preview(match: str) -> str:
    """A short, single-line preview of a matched marker."""
    flat = " ".join(match.split())
    return flat if len(flat) <= _PREVIEW else flat[:_PREVIEW] + "…"


def _resolve_spans(text: str, spans: list[tuple[int, int, str, str]]) -> tuple[str, list[dict]]:
    """Build tagged text + findings from raw ``(start, end, type, match)`` spans.

    Spans are resolved left-to-right, longest-first, so overlapping matches never
    double-tag or corrupt offsets. Shared by the regex detectors and ``--llm``.
    """
    # Sort by start, then longest-first so we keep the widest span when two
    # detectors fire on the same region.
    spans = sorted(spans, key=lambda s: (s[0], -(s[1] - s[0])))

    findings: list[dict] = []
    out: list[str] = []
    cursor = 0
    for start, end, name, match in spans:
        if start < cursor:
            # Overlaps an already-tagged span — skip to avoid double tagging.
            continue
        out.append(text[cursor:start])
        out.append(f"[FOLD:{name}]")
        findings.append({"type": name, "match": match, "start": start, "end": end})
        cursor = end
    out.append(text[cursor:])

    return "".join(out), findings


def fold(
    text: str,
    types: set[str] | None = None,
    detectors: dict[str, re.Pattern[str]] | None = None,
) -> tuple[str, list[dict]]:
    """Flag overconfidence markers in ``text``.

    Returns ``(tagged_text, findings)`` where each finding is
    ``{"type", "match", "start", "end"}`` against the *original* text and the
    tagged text replaces each marker with ``[FOLD:type]``. ``types`` optionally
    restricts which detectors run (default: all). ``detectors`` overrides the
    detector table (default: the built-ins) — used to fold in custom patterns.

    Overlapping matches are resolved left-to-right, longest-first, so offsets
    stay sane and the rebuilt text never gets corrupted. Calibrated, hedged
    text comes back untouched with an empty findings list.
    """
    table = _DETECTORS if detectors is None else detectors
    active = set(table) if types is None else (set(types) & set(table))

    # Collect every span from every active detector.
    spans: list[tuple[int, int, str, str]] = []
    for name in table:
        if name not in active:
            continue
        for m in table[name].finditer(text):
            spans.append((m.start(), m.end(), name, m.group(0)))

    return _resolve_spans(text, spans)


def _summary_lines(findings: list[dict]) -> list[str]:
    """Human-readable lines for a findings list: type, preview, offset."""
    return [f"{f['type']}\t{_preview(f['match'])}\t@{f['start']}" for f in findings]


def _tally(findings: list[dict]) -> str:
    """A `2×certainty, 1×absolute` style tally, sorted by type."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["type"]] = counts.get(f["type"], 0) + 1
    return ", ".join(f"{n}×{t}" for t, n in sorted(counts.items()))


def _inflation_score(text: str, findings: list[dict]) -> float:
    """Confidence-inflation: overconfidence markers per 100 words."""
    words = len(text.split())
    if not words:
        return 0.0
    return round(len(findings) * 100.0 / words, 2)


# --- custom detectors -----------------------------------------------------
# Built-ins are the base; user-supplied entries merge in and override by name.
# A pattern file is JSON shaped {"detectors": {"<type>": "<regex>"}}; each regex
# compiles case-insensitively, exactly like the built-ins. Affects offline mode
# only — --llm judges tone directly and ignores the detector table.


def load_patterns(files: list[str]) -> dict[str, re.Pattern[str]]:
    """Merge custom detectors from ``files`` onto the built-in table.

    Each file is JSON ``{"detectors": {"<type>": "<regex>"}}``. Later files (and
    user entries that reuse a built-in name) override earlier ones. Returns a
    fresh detector table; raises ``ValueError`` on a malformed file or regex.
    """
    table = dict(_DETECTORS)
    for path in files:
        with open(path, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}: invalid JSON ({e})") from e
        dets = data.get("detectors") if isinstance(data, dict) else None
        if not isinstance(dets, dict):
            raise ValueError(f'{path}: expected {{"detectors": {{"<type>": "<regex>"}}}}')
        for name, pattern in dets.items():
            if not isinstance(pattern, str):
                raise ValueError(f"{path}: detector {name!r} must map to a regex string")
            try:
                table[name] = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                raise ValueError(f"{path}: detector {name!r} has a bad regex ({e})") from e
    return table


# --- model-backed detection (opt-in) --------------------------------------
# The regex detectors above flag *words* ("always", "definitely"). They can't
# tell an earned absolute from an unearned one. `--llm` asks a model to judge
# the confidence-vs-evidence relationship: it flags statements whose certainty
# isn't backed by the surrounding evidence, even when no tell-word appears, and
# leaves calibrated/hedged prose alone.

_LLM_TYPES = ("certainty", "no_doubt", "absolute", "false_authority", "unearned_confidence")

_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(_LLM_TYPES)},
                    "snippet": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["type", "snippet", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

_LLM_SYSTEM = (
    "You judge overconfident TONE relative to evidence — not whether facts are "
    "true. Read the text and flag statements whose confidence is NOT earned by "
    "the evidence present: sweeping absolutes with no proof, bare certainty, "
    "doubt-erasing phrasing, borrowed authority ('trust me', 'everyone knows'), "
    "or any claim asserted far more confidently than its support warrants — even "
    "when no obvious tell-word like 'always' appears. Do NOT flag a confident "
    "claim that the text actually backs up, and do NOT flag calibrated or hedged "
    "language. For each flagged statement return its type (one of: certainty, "
    "no_doubt, absolute, false_authority, unearned_confidence), the exact "
    "verbatim snippet copied from the text, and a one-line reason. Calibrated or "
    "well-hedged text returns an empty list."
)


def fold_llm(
    text: str,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, list[dict]]:
    """Model-backed overconfidence check — judges tone vs. evidence, not words.

    Same return shape as :func:`fold`: ``(tagged_text, findings)`` where each
    finding is ``{"type", "match", "start", "end"}``. The model returns
    ``{type, snippet, reason}`` items; each snippet is located verbatim in the
    original text via ``str.find`` to compute offsets and reuse fold's span
    resolution. A snippet not found verbatim is still reported as a finding with
    ``start``/``end`` of ``-1`` but is not tagged. Raises ``LLMError``
    on provider failure so the caller can exit cleanly.
    """
    if not text.strip():
        return text, []
    prompt = f"TEXT:\n{text}\n\nFlag every statement whose confidence the evidence doesn't earn."
    data = llm_complete(
        prompt, system=_LLM_SYSTEM, schema=_LLM_SCHEMA, provider=provider, model=model
    )

    spans: list[tuple[int, int, str, str]] = []
    unlocated: list[dict] = []
    for item in data.get("findings", []):
        name = item.get("type") or "unearned_confidence"
        snippet = item.get("snippet") or ""
        idx = text.find(snippet) if snippet else -1
        if idx == -1:
            unlocated.append({"type": name, "match": snippet, "start": -1, "end": -1})
            continue
        spans.append((idx, idx + len(snippet), name, snippet))

    tagged, findings = _resolve_spans(text, spans)
    findings.extend(unlocated)
    return tagged, findings


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(
        prog="fold",
        description="know when to fold.",
    )
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument(
        "--check",
        action="store_true",
        help="print nothing; exit 1 if any overconfidence marker is found (gates a check)",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="list markers (type + preview + offset) to stdout; exit 0",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit findings as JSON",
    )
    p.add_argument(
        "--score",
        action="store_true",
        help="print a single confidence-inflation score (markers per 100 words)",
    )
    p.add_argument(
        "--only",
        metavar="t1,t2",
        help="restrict to a comma-separated list of marker types",
    )
    p.add_argument(
        "--patterns",
        action="append",
        default=[],
        metavar="FILE",
        help='merge custom detectors from a JSON file {"detectors": {"<type>": "<regex>"}} '
        "(repeatable; offline mode only). Falls back to $FOLD_PATTERNS.",
    )
    add_llm_args(p)
    args = p.parse_args(argv)

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    # --llm: let a model judge unearned confidence (ignores the detector table).
    if args.llm:
        try:
            tagged, findings = fold_llm(raw, provider=args.provider, model=args.model)
        except LLMError as e:
            sys.stderr.write(f"[fold] llm mode failed: {e}\n")
            return 2
    else:
        # Custom detectors: --patterns FILE (repeatable), else $FOLD_PATTERNS.
        pattern_files = list(args.patterns)
        if not pattern_files and os.environ.get("FOLD_PATTERNS"):
            pattern_files = [p for p in os.environ["FOLD_PATTERNS"].split(os.pathsep) if p]
        try:
            detectors = load_patterns(pattern_files) if pattern_files else _DETECTORS
        except (OSError, ValueError) as e:
            sys.stderr.write(f"[fold] bad --patterns: {e}\n")
            return 2

        # Resolve which detectors run.
        if args.only:
            wanted = {t.strip() for t in args.only.split(",") if t.strip()}
            unknown = wanted - set(detectors)
            if unknown:
                sys.stderr.write(
                    f"[fold] unknown marker(s): {', '.join(sorted(unknown))}\n"
                    f"[fold] known: {', '.join(sorted(detectors))}\n"
                )
                return 2
            types: set[str] | None = wanted
        else:
            types = None

        tagged, findings = fold(raw, types, detectors=detectors)

    # --score: a quick gauge of how much the draft is bluffing.
    if args.score:
        score = _inflation_score(raw, findings)
        sys.stdout.write(
            f"[fold] confidence-inflation: {score} markers/100w ({len(findings)} tells)\n"
        )
        return 1 if (args.check and findings) else 0

    # --json: structured findings to stdout.
    if args.json:
        payload = [
            {
                "type": f["type"],
                "preview": _preview(f["match"]),
                "start": f["start"],
                "end": f["end"],
            }
            for f in findings
        ]
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 1 if (args.check and findings) else 0

    # --report: list the tells to stdout, exit 0.
    if args.report:
        if findings:
            sys.stdout.write("\n".join(_summary_lines(findings)) + "\n")
        else:
            sys.stdout.write("clean — nothing to fold\n")
        return 0

    # Summary to stderr in every non-json, non-report mode.
    if findings:
        sys.stderr.write(f"[fold] {len(findings)} tells: {_tally(findings)}\n")
    else:
        sys.stderr.write("[fold] clean — nothing to fold\n")

    # --check: gate mode. No tagged text, exit 1 on any tell.
    if args.check:
        return 1 if findings else 0

    # Default: print the tagged text so the bluffing spots are visible.
    sys.stdout.write(tagged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
