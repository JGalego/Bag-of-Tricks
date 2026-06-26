#!/usr/bin/env python3
"""alibi — does the story check out?

A grounding / faithfulness checker. Takes an ANSWER and one or more SOURCE
documents, splits the answer into sentences (claims), and flags every claim
that has no support in the sources. bluff checks the links; alibi checks the
story. The default check is zero-dependency, deterministic, lexical overlap;
``--llm`` swaps in a real entailment judgment (Anthropic / OpenAI / Gemini) that
catches paraphrase and contradiction the overlap score misses.

    alibi.py answer.txt --source sources.txt
    cat answer.txt | alibi.py --source-text "the ground truth ..."
    alibi.py answer.txt --source a.txt --source b.txt --check   # gate a RAG run
    alibi.py answer.txt --source sources.txt --json
    alibi.py answer.txt --source sources.txt --llm   # model-backed grounding
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
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
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

# Sentence splitter: break on . ! ? followed by whitespace, but not after a
# short run that looks like an abbreviation (e.g. "U.S.", "etc.", "Dr."). This
# is deliberately simple — good enough to carve an answer into claims, not a
# linguistics project.
_ABBREV = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "vs",
        "etc",
        "e.g",
        "i.e",
        "fig",
        "no",
        "inc",
        "ltd",
        "co",
        "corp",
        "u.s",
        "u.k",
        "approx",
    }
)

# A boundary is end-punctuation + whitespace. We split there, then stitch back
# any split that landed right after an abbreviation.
_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Content tokens: runs of letters/digits (with internal apostrophes/hyphens).
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")

# A small, boring stopword set. Pulling these before scoring keeps "the sky is
# blue" from scoring high against a source that merely contains "the" and "is".
# The second line is conversational filler — greetings and chatty connective
# tissue ("Sure!", "Of course, here you go.") that an LLM tacks on. Stripping
# it means a pure-greeting sentence ends up with no content words and is treated
# as neutral, not flagged as a fabricated claim.
_STOPWORDS = frozenset(
    """
    a an and are as at be been being but by can could did do does doing done
    for from had has have having he her hers him his how i if in into is it its
    me my no nor not of off on once only or other our ours out over own same she
    should so some such than that the their theirs them then there these they this
    those through to too under until up very was we were what when where which
    while who whom why will with would you your yours
    sure okay ok yes yeah yep nope hi hello hey thanks please certainly absolutely
    course here go great sorry well alright cheers
    """.split()
)


def _tokenize(text: str) -> list[str]:
    """Lowercase content words with stopwords and punctuation stripped."""
    return [w for w in (m.group(0).lower() for m in _WORD_RE.finditer(text)) if w not in _STOPWORDS]


def _bigrams(tokens: list[str]) -> list[str]:
    """Adjacent content-word pairs — cheap phrase-level signal."""
    return [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]


def split_sentences(text: str) -> list[str]:
    """Carve text into sentence-shaped claims.

    Splits on .!? + whitespace, then re-joins a fragment back onto the previous
    one when the previous fragment ended in a known abbreviation (so "Dr. Smith
    agrees." stays one claim). Blank fragments are dropped.
    """
    pieces = _SPLIT_RE.split(text.strip())
    out: list[str] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if out:
            last = out[-1]
            tail = last[:-1] if last and last[-1] in ".!?" else last
            last_word = _WORD_RE.findall(tail.lower())
            if last_word and last_word[-1] in _ABBREV:
                out[-1] = f"{last} {piece}"
                continue
        out.append(piece)
    return out


def _support_score(
    claim_tokens: list[str], source_unigrams: set[str], source_bigrams: set[str]
) -> float:
    """Fraction of a claim's content that the source corroborates.

    Combines unigram and bigram overlap: a claim scores high only when its
    *words* appear in the source AND (weighted) its word *pairs* do too, so a
    sentence that reuses the source's vocabulary in a different order doesn't
    sail through as easily. Pure lexical overlap — no semantics.
    """
    if not claim_tokens:
        return 1.0  # no content to corroborate — treated as neutral/supported
    uni_hits = sum(1 for t in claim_tokens if t in source_unigrams)
    uni = uni_hits / len(claim_tokens)

    bigs = _bigrams(claim_tokens)
    if bigs:
        big_hits = sum(1 for b in bigs if b in source_bigrams)
        big = big_hits / len(bigs)
        # Lean on unigrams (the primary signal); bigrams sharpen the verdict.
        return 0.75 * uni + 0.25 * big
    return uni


def alibi(answer: str, sources: str, threshold: float = 0.5) -> list[dict]:
    """Check each claim in ``answer`` against ``sources``.

    Returns one dict per claim: ``{"claim", "score", "supported"}``. A claim is
    SUPPORTED when its lexical support score meets ``threshold``. Claims with no
    content words (e.g. "Sure!") score 1.0 and pass — there's nothing to ground.

    Pure and deterministic: same inputs, same output, no network, no model.
    """
    source_tokens = _tokenize(sources)
    source_unigrams = set(source_tokens)
    source_bigrams = set(_bigrams(source_tokens))

    results: list[dict] = []
    for claim in split_sentences(answer):
        tokens = _tokenize(claim)
        score = _support_score(tokens, source_unigrams, source_bigrams)
        results.append(
            {
                "claim": claim,
                "score": round(score, 3),
                "supported": score >= threshold,
            }
        )
    return results


# --- model-backed grounding (opt-in) --------------------------------------
# The lexical check above is fast, deterministic, and zero-dependency, but it is
# blind to paraphrase and—worse—can mark a claim that CONTRADICTS the sources as
# supported when it reuses their vocabulary. `--llm` swaps the overlap score for
# a real entailment judgment from a model (Anthropic / OpenAI / Gemini).

_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "score": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["index", "score", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}

_LLM_SYSTEM = (
    "You are a strict grounding / faithfulness checker for RAG. You are given "
    "SOURCE material and a numbered list of CLAIMS taken from an answer. For each "
    "claim, return a grounding score in [0,1]: 1.0 = fully entailed by the "
    "sources, 0.0 = unsupported or contradicted. Judge meaning, not word overlap: "
    "a paraphrase the sources entail scores high; a claim that CONTRADICTS the "
    "sources scores near 0 even if it reuses their vocabulary; a claim the sources "
    "simply don't mention scores low. Claims with no factual content (greetings, "
    "filler) score 1.0. Give a one-line reason for each."
)


def alibi_llm(
    answer: str,
    sources: str,
    threshold: float = 0.5,
    provider: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """Model-backed grounding check — semantic entailment, not lexical overlap.

    Same return shape as :func:`alibi` (``claim`` / ``score`` / ``supported``)
    plus a ``reason`` per claim. Raises ``LLMError`` on provider failure
    so the caller can fall back or exit cleanly.
    """
    claims = split_sentences(answer)
    if not claims:
        return []
    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(claims))
    prompt = f"SOURCES:\n{sources}\n\nCLAIMS:\n{numbered}\n\nScore every claim by its index."
    data = llm_complete(
        prompt, system=_LLM_SYSTEM, schema=_LLM_SCHEMA, provider=provider, model=model
    )
    scored = {item.get("index"): item for item in data.get("claims", [])}
    results: list[dict] = []
    for i, claim in enumerate(claims):
        item = scored.get(i, {})
        score = max(0.0, min(1.0, float(item.get("score", 0.0))))
        results.append(
            {
                "claim": claim,
                "score": round(score, 3),
                "supported": score >= threshold,
                "reason": item.get("reason", ""),
            }
        )
    return results


def _format(result: dict) -> str:
    mark = "SUPPORTED  " if result["supported"] else "UNSUPPORTED"
    return f"{mark} [{result['score']:.2f}] {result['claim']}"


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(prog="alibi", description="does the story check out?")
    p.add_argument("files", nargs="*", help="answer file(s) to check (default: stdin)")
    p.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="FILE",
        help="a source/ground-truth file (repeatable)",
    )
    p.add_argument(
        "--source-text",
        action="append",
        default=[],
        metavar="TEXT",
        help="source text passed inline (repeatable)",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="support cutoff; below this a claim is UNSUPPORTED (default: 0.5)",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="print nothing; exit 1 if any claim is unsupported (gates a pipeline)",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="print only the unsupported claims to stdout; exit 0",
    )
    p.add_argument("--json", action="store_true", help="emit structured per-claim JSON results")
    add_llm_args(p)
    args = p.parse_args(argv)

    answer = (
        "".join(open(f, encoding="utf-8").read() for f in args.files)
        if args.files
        else sys.stdin.read()
    )

    source_parts = [open(f, encoding="utf-8").read() for f in args.source]
    source_parts += list(args.source_text)
    if not source_parts:
        sys.stderr.write('[alibi] no sources given — use --source FILE or --source-text "..."\n')
        return 2
    sources = "\n".join(source_parts)

    if args.llm:
        try:
            results = alibi_llm(
                answer,
                sources,
                threshold=args.threshold,
                provider=args.provider,
                model=args.model,
            )
        except LLMError as e:
            sys.stderr.write(f"[alibi] llm mode failed: {e}\n")
            return 2
    else:
        results = alibi(answer, sources, threshold=args.threshold)
    unsupported = [r for r in results if not r["supported"]]

    if args.json:
        sys.stdout.write(json.dumps(results, indent=2) + "\n")
        return 1 if (args.check and unsupported) else 0

    if args.check:
        return 1 if unsupported else 0

    if args.report:
        if unsupported:
            sys.stdout.write("\n".join(_format(r) for r in unsupported) + "\n")
        else:
            sys.stdout.write("clean — every claim checks out\n")
        return 0

    # Default: per-claim verdict report to stdout, summary to stderr.
    for r in results:
        sys.stdout.write(_format(r) + "\n")
    supported = len(results) - len(unsupported)
    sys.stderr.write(
        f"[alibi] {len(results)} claim(s): {supported} supported, {len(unsupported)} unsupported\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
