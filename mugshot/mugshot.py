#!/usr/bin/env python3
"""mugshot — we know your prints.

Given a chunk of text, mugshot guesses which model or family most likely wrote
it and shows the prints it matched. It is a probabilistic guess, not forensic
proof: models drift, mimic each other, and a deliberate human can fake any
style. Treat the verdict as a hunch.

By DEFAULT mugshot asks a model — a real LLM authorship/stylometry pass — when a
provider key is configured. With no key (and no `--llm`) it falls back to the
offline regex heuristic (the old "parlor trick") and says so on stderr. Force
either path with `--llm` (model) or `--parlor` (regex).

Where `tell` flags the giveaways in AI prose, mugshot uses those same prints to
*name a suspect* — it lines the families up and points at the most likely one.

    echo "Certainly! I'd be happy to help. It's important to note..." | mugshot.py
    -> most likely: gpt-ish (medium confidence) — probabilistic guess, not proof

    mugshot.py --report draft.md   # every matched print + offset
    mugshot.py --all draft.md      # full ranked scoreboard
    mugshot.py --json draft.md     # the structured verdict
    mugshot.py --llm draft.md      # force the model-backed pass
    mugshot.py --parlor draft.md   # force the offline regex heuristic

Custom parlor prints can be merged in via ``--patterns FILE`` (repeatable) or
the ``MUGSHOT_PATTERNS`` env var (os.pathsep-separated paths). The JSON shape::

    {
      "suspects": {
        "<suspect-name>": [
          [<weight:number>, "<label>", "<regex>"],
          ...
        ]
      }
    }

Each inner triple is one print: a weight, a human label, and a case-insensitive
regex. New suspect names create new lineup rows; existing names are extended.
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

# --- the line-up ----------------------------------------------------------
# Each SUSPECT is a stylistic profile: a list of (weight, label, regex) prints.
# Weights are deliberately coarse — these are hunches, not measurements. A high
# weight means "if you see this, lean hard"; a low weight means "mild tell".
# Matches are case-insensitive. Edit these freely; they are caricatures, not
# science. Models drift and copy each other, so none of this is definitive.

# A "print" tuple: (weight, label, pattern).
_Print = tuple[float, str, str]

SUSPECTS: dict[str, list[_Print]] = {
    # The eager assistant: opener exclamations, hedging boilerplate, bolded
    # section headers, numbered listicles, tidy windups.
    "gpt-ish": [
        (3.0, "Certainly! opener", r"\bcertainly[!,]"),
        (2.5, "I'd be happy to", r"\bi'?d be happy to\b"),
        (2.5, "It's important to note", r"\bit'?s important to (?:note|remember)\b"),
        (2.0, "However, it's worth", r"\bhowever,\s+it'?s worth\b"),
        (1.5, "In conclusion", r"\bin conclusion\b"),
        (1.5, "Overall,", r"(?m)^\s*overall,"),
        (1.5, "bold header", r"(?m)^\s*\*\*[^*\n]+\*\*\s*:?\s*$"),
        (1.0, "numbered listicle", r"(?m)^\s*\d+\.\s+\S"),
        (1.0, "I hope this helps", r"\bi hope this helps\b"),
        (1.0, "Sure, here's", r"\bsure,\s+here'?s\b"),
    ],
    # The warm collaborator: first-person leads, em-dash asides, gentle
    # praise, "let me / here's" framing.
    "claude-ish": [
        (2.5, "I'll … lead", r"(?m)^\s*i'?ll\s+\w+"),
        (2.0, "Let me … lead", r"(?m)^\s*let me\s+\w+"),
        (2.0, "Here's … lead", r"(?m)^\s*here'?s\s+\w+"),
        (2.5, "Great question", r"\bgreat question\b"),
        (1.5, "Sure, opener", r"(?m)^\s*sure[!,]"),
        (1.5, "happy to help (warm)", r"\bhappy to help\b"),
        (1.0, "em-dash aside", r"—"),
        (1.0, "worth keeping in mind", r"\bworth keeping in mind\b"),
        (1.0, "a couple of things", r"\ba (?:couple|few) (?:of )?things\b"),
    ],
    # The universal tells — the prints any model leaves (borrowed from `tell`).
    # These don't pin a family; they just confirm "a model was here".
    "generic-AI": [
        (2.0, "delve", r"\bdelve\b"),
        (2.0, "tapestry", r"\btapestry\b"),
        (2.0, "navigate the complexities", r"\bnavigat\w*\s+the\s+complexit\w+\b"),
        (2.5, "it's not just X, it's Y", r"\bit'?s not just\b[^.!?\n]*?,?\s*it'?s\b"),
        (2.0, "in today's fast-paced", r"\bin today'?s fast[- ]paced\b"),
        (1.5, "testament to", r"\ba testament to\b"),
        (1.5, "ever-evolving", r"\bever[- ]evolving\b"),
        (1.0, "crucial", r"\bcrucial\b"),
        (1.0, "leverage", r"\bleverage\b"),
        (1.0, "robust", r"\brobust\b"),
    ],
}

# Score separations and absolute hit counts get bucketed into these confidence
# bands. Everything here is a judgement call, not a calibration.
_HIGH_MARGIN = 2.5  # top score must beat the runner-up by at least this …
_HIGH_HITS = 3.0  # … and the top score itself must clear this.
_MED_MARGIN = 1.0
_MED_HITS = 1.5

# Below this, we don't accuse anyone.
_FLOOR = 1.0


def _compile() -> dict[str, list[tuple[float, str, re.Pattern[str]]]]:
    """Pre-compile every suspect's prints (case-insensitive)."""
    out: dict[str, list[tuple[float, str, re.Pattern[str]]]] = {}
    for suspect, prints in SUSPECTS.items():
        out[suspect] = [
            (weight, label, re.compile(pat, re.IGNORECASE)) for weight, label, pat in prints
        ]
    return out


_COMPILED = _compile()


def merge_suspects(extra: dict[str, list]) -> None:
    """Merge custom prints into ``SUSPECTS`` and recompile the matchers.

    ``extra`` maps suspect name -> list of ``[weight, label, regex]`` triples.
    New names create new lineup rows; existing names are extended in place.
    """
    for suspect, prints in extra.items():
        rows: list[_Print] = []
        for triple in prints:
            weight, label, pat = triple
            rows.append((float(weight), str(label), str(pat)))
        SUSPECTS.setdefault(suspect, []).extend(rows)
    global _COMPILED
    _COMPILED = _compile()


def load_patterns(path: str) -> dict[str, list]:
    """Load a custom-patterns JSON file: ``{"suspects": {name: [[w,l,re],...]}}``."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    suspects = data.get("suspects", {})
    if not isinstance(suspects, dict):
        raise ValueError(f"{path}: 'suspects' must be an object")
    return suspects


def _apply_pattern_files(paths: list[str]) -> None:
    """Merge each patterns file in order; later files extend earlier ones."""
    for path in paths:
        merge_suspects(load_patterns(path))


def _count_words(text: str) -> int:
    return max(1, len(re.findall(r"\b\w+\b", text)))


def _confidence(top: float, runner_up: float) -> str:
    """Bucket a verdict into low/medium/high from absolute score + separation."""
    margin = top - runner_up
    if top >= _HIGH_HITS and margin >= _HIGH_MARGIN:
        return "high"
    if top >= _MED_HITS and margin >= _MED_MARGIN:
        return "medium"
    return "low"


def mugshot(text: str) -> dict:
    """Guess who wrote ``text`` from stylistic fingerprints.

    Returns a dict::

        {
          "verdict":    <suspect name or "human / inconclusive">,
          "confidence": "low" | "medium" | "high",
          "scores":     {suspect: weighted_score, ...},
          "prints":     [{"suspect", "match", "label", "start", "weight"}, ...],
        }

    Scores are the summed weights of matched prints, lightly normalized by
    length so a long document of mild tells doesn't out-shout a short, blatant
    one. This is a heuristic guess — models drift and mimic each other, and a
    human can fake any style — never read it as proof of authorship.
    """
    words = _count_words(text)
    # Gentle length normalization: long texts naturally accrue more raw hits,
    # so divide the raw weight by a slow function of length. sqrt keeps short
    # damning passages punchy while not letting essays win on volume alone.
    norm = (words / 100.0) ** 0.5
    norm = norm if norm >= 1.0 else 1.0

    prints: list[dict] = []
    raw: dict[str, float] = {}
    for suspect, compiled in _COMPILED.items():
        total = 0.0
        for weight, label, rx in compiled:
            for m in rx.finditer(text):
                total += weight
                prints.append(
                    {
                        "suspect": suspect,
                        "match": m.group(0),
                        "label": label,
                        "start": m.start(),
                        "weight": weight,
                    }
                )
        raw[suspect] = total

    scores = {s: round(v / norm, 3) for s, v in raw.items()}

    # Rank: highest score first; ties broken by suspect name for determinism.
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    top_name, top_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

    if top_score < _FLOOR:
        verdict = "human / inconclusive"
        confidence = "low"
    else:
        verdict = top_name
        confidence = _confidence(top_score, runner_up)

    # Prints sorted by offset for a stable, readable report.
    prints.sort(key=lambda p: (p["start"], p["suspect"]))

    return {
        "verdict": verdict,
        "confidence": confidence,
        "scores": scores,
        "prints": prints,
    }


# --- model-backed attribution (the default when a key is set) -------------
# The regex lineup above is fast, deterministic, and offline, but it only knows
# the caricatures hard-coded into SUSPECTS. A real model can read a passage's
# style — cadence, hedging, structure — and name a likely author family from
# evidence the regexes never encode. `--llm` (and the default, when a provider
# key is configured) swaps the parlor trick for that judgment.

_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "family": {"type": "string"},
                    "score": {"type": "number"},
                },
                "required": ["family", "score"],
                "additionalProperties": False,
            },
        },
        "prints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "suspect": {"type": "string"},
                    "match": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["suspect", "match", "label"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdict", "confidence", "scores", "prints"],
    "additionalProperties": False,
}

_LLM_SYSTEM = (
    "You are an expert at LLM authorship attribution and stylometry. Given a "
    "passage, name the SINGLE most likely model family that wrote it — one of "
    "gpt/openai, claude/anthropic, gemini/google, llama, generic-AI, or human "
    "(use 'human / inconclusive' when it reads human or the evidence is weak). "
    "Judge style, not subject: openers, hedges, structure, list shapes, "
    "punctuation habits, cadence. Return:\n"
    "- verdict: the most likely family (or 'human / inconclusive')\n"
    "- confidence: low | medium | high, honest about uncertainty\n"
    "- scores: every family you weighed, each with a probability in [0,1]\n"
    "- prints: the specific spans of evidence you relied on, quoted verbatim "
    "from the text, each with a short label\n"
    "Be honest: this is a probabilistic guess from style, not proof of "
    "authorship. Models drift and mimic each other and a human can fake any "
    "style. When nothing is distinctive, say 'human / inconclusive' at low "
    "confidence rather than forcing an accusation."
)


def mugshot_llm(text: str, provider: str | None = None, model: str | None = None) -> dict:
    """Model-backed authorship attribution — same shape as :func:`mugshot`.

    Returns ``{"verdict", "confidence", "scores", "prints"}`` where ``verdict``
    is the most likely model family (or ``"human / inconclusive"``), ``scores``
    maps family -> float in [0,1], and ``prints`` is a list of
    ``{"suspect", "match", "label", "start", "weight"}`` (offsets located via
    ``str.find`` when possible, else ``start=-1``/``weight=1.0``).

    Raises ``LLMError`` on provider failure so the caller can fall back
    or exit cleanly.
    """
    prompt = f"Attribute the authorship of this passage:\n\n{text}"
    data = llm_complete(
        prompt, system=_LLM_SYSTEM, schema=_LLM_SCHEMA, provider=provider, model=model
    )

    verdict = str(data.get("verdict") or "human / inconclusive").strip()
    confidence = str(data.get("confidence") or "low").strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"

    scores: dict[str, float] = {}
    for item in data.get("scores", []):
        family = str(item.get("family", "")).strip()
        if not family:
            continue
        scores[family] = round(max(0.0, min(1.0, float(item.get("score", 0.0)))), 3)

    prints: list[dict] = []
    for item in data.get("prints", []):
        match = str(item.get("match", ""))
        start = text.find(match) if match else -1
        prints.append(
            {
                "suspect": str(item.get("suspect", verdict)),
                "match": match,
                "label": str(item.get("label", "")),
                "start": start,
                "weight": 1.0,
            }
        )
    # Keep prints in offset order where we have offsets, like the parlor path.
    prints.sort(key=lambda p: (p["start"] < 0, p["start"], p["suspect"]))

    return {
        "verdict": verdict,
        "confidence": confidence,
        "scores": scores,
        "prints": prints,
    }


_PREVIEW = 32


def _preview(match: str) -> str:
    """A short, single-line preview of a matched print."""
    one_line = " ".join(match.split())
    if len(one_line) > _PREVIEW:
        return one_line[:_PREVIEW] + "…"
    return one_line


def _verdict_line(result: dict) -> str:
    verdict = result["verdict"]
    if verdict == "human / inconclusive":
        return "inconclusive — no strong prints; could be human. (heuristic, not proof)"
    return f"most likely: {verdict} ({result['confidence']} confidence) — heuristic, not proof"


def _report_lines(result: dict) -> list[str]:
    """Every matched print: suspect, preview, offset."""
    lines = [_verdict_line(result), ""]
    if not result["prints"]:
        lines.append("no prints lifted — clean.")
        return lines
    lines.append("prints lifted:")
    for p in result["prints"]:
        lines.append(f"  {p['suspect']:<12} {_preview(p['match']):<34} @{p['start']}")
    return lines


def _scoreboard_lines(result: dict) -> list[str]:
    """The full ranked line-up of every suspect."""
    lines = [_verdict_line(result), "", "line-up (weighted, length-normalized):"]
    ranked = sorted(result["scores"].items(), key=lambda kv: (-kv[1], kv[0]))
    for suspect, score in ranked:
        marker = " <-- most likely" if suspect == result["verdict"] else ""
        lines.append(f"  {suspect:<12} {score:>7.3f}{marker}")
    return lines


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(prog="mugshot", description="we know your prints.")
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument(
        "--report",
        action="store_true",
        help="list every matched print (suspect + preview + offset)",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="show the full ranked scoreboard of all suspects",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit the full structured verdict as JSON",
    )
    p.add_argument(
        "--parlor",
        action="store_true",
        help="force the offline regex heuristic (the parlor trick)",
    )
    p.add_argument(
        "--patterns",
        action="append",
        default=[],
        metavar="FILE",
        help="merge custom parlor prints from a JSON file (repeatable)",
    )
    add_llm_args(p)
    args = p.parse_args(argv)

    # Custom prints: explicit --patterns win, else the MUGSHOT_PATTERNS env var.
    pattern_files = list(args.patterns)
    if not pattern_files and os.environ.get("MUGSHOT_PATTERNS"):
        pattern_files = [p for p in os.environ["MUGSHOT_PATTERNS"].split(os.pathsep) if p.strip()]
    if pattern_files:
        try:
            _apply_pattern_files(pattern_files)
        except (OSError, ValueError, json.JSONDecodeError, re.error) as e:
            sys.stderr.write(f"[mugshot] could not load patterns: {e}\n")
            return 2

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    # Path selection:
    #   --parlor          -> always the offline regex heuristic
    #   --llm             -> always the model (fail loud, no silent fallback)
    #   neither (default) -> model if a provider key is configured, else parlor
    #                        (with a note that real attribution needs a key)
    if args.parlor:
        result = mugshot(raw)
    elif args.llm:
        try:
            result = mugshot_llm(raw, provider=args.provider, model=args.model)
        except LLMError as e:
            sys.stderr.write(f"[mugshot] llm mode failed: {e}\n")
            return 2
    elif llm_available(args.provider):
        try:
            result = mugshot_llm(raw, provider=args.provider, model=args.model)
        except LLMError as e:
            sys.stderr.write(
                f"[mugshot] llm mode failed ({e}); falling back to the offline heuristic\n"
            )
            result = mugshot(raw)
    else:
        sys.stderr.write(
            "[mugshot] no provider key configured — using the offline regex heuristic. "
            "Set an API key (or pass --llm) for real model-backed attribution.\n"
        )
        result = mugshot(raw)

    if args.json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    elif args.report:
        sys.stdout.write("\n".join(_report_lines(result)) + "\n")
    elif args.all:
        sys.stdout.write("\n".join(_scoreboard_lines(result)) + "\n")
    else:
        sys.stdout.write(_verdict_line(result) + "\n")
        if result["prints"]:
            shown = ", ".join(
                f"{p['suspect']}:{_preview(p['match'])}" for p in result["prints"][:6]
            )
            sys.stdout.write(f"prints: {shown}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
