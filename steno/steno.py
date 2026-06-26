#!/usr/bin/env python3
"""steno — two letters, and the prompt writes itself.

Mind-numbingly short aliases for the prompts you type all day. `steno r app.py`
expands the alias `r` into a full "review this code…" prompt with the file's
contents spliced in, and prints it — pipe it into any LLM, or pass `--run` to
send it to Claude directly.

    steno r src/app.py            # review  -> prints the expanded prompt
    steno t utils.py              # tests
    steno c                       # commit message from `git diff --cached`
    steno e parser.py | deadpan   # compose with the rest of the bag
    steno rx "match an iso date"  # free-text input instead of a file
    steno r app.py --run          # actually send it to an LLM (any provider)
    steno ls                      # list every alias

Add your own in one line: put `alias  the prompt text {input}` lines in
~/.config/steno/aliases.txt (or point $STENO_ALIASES at a file). User aliases
extend and override the built-ins.

Expanding needs nothing but Python 3.9+. `--run` works with any of
ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY, plus that provider's SDK
(pip install anthropic / openai / google-genai). Pick a
provider explicitly with `--provider {anthropic,openai,gemini}` or let it
auto-detect from whichever key is set.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
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

# alias -> (human name, template). {input} is where the target gets spliced in.
BUILTINS: dict[str, tuple[str, str]] = {
    "e": ("explain", "Explain what the following does, clearly and concisely.\n\n{input}"),
    "r": (
        "review",
        "Review the following code for bugs, edge cases, and clarity issues. "
        "Be specific and cite the relevant lines.\n\n{input}",
    ),
    "t": (
        "tests",
        "Write thorough tests for the following code. Cover edge cases and "
        "failure modes.\n\n{input}",
    ),
    "d": (
        "docstring",
        "Add clear docstrings and comments to the following code. Return the "
        "full updated code.\n\n{input}",
    ),
    "ty": (
        "types",
        "Add precise type annotations to the following code. Return the full "
        "updated code.\n\n{input}",
    ),
    "f": (
        "fix",
        "Find and fix the bugs in the following code. Briefly explain each fix, "
        "then return the corrected code.\n\n{input}",
    ),
    "o": (
        "optimize",
        "Optimize the following code for performance without changing its "
        "behavior. Explain the key changes.\n\n{input}",
    ),
    "s": (
        "simplify",
        "Simplify the following code for readability without changing its "
        "behavior. Return the full updated code.\n\n{input}",
    ),
    "n": (
        "names",
        "Suggest clearer names for the identifiers in the following code, with a "
        "short rationale for each.\n\n{input}",
    ),
    "rx": (
        "regex",
        "Write a regular expression for the following requirement. Explain it and "
        "give a few test cases.\n\n{input}",
    ),
    "sql": (
        "sql",
        "Write a SQL query for the following requirement. State any assumptions.\n\n{input}",
    ),
    "sh": (
        "shell",
        "Write a shell command for the following task. Briefly explain each flag.\n\n{input}",
    ),
    "tl": ("tldr", "Summarize the following in a few tight bullet points.\n\n{input}"),
    "c": (
        "commit",
        "Write a concise commit message (Conventional Commits style) for the "
        "following diff. Output only the message.\n\n{input}",
    ),
    "pr": (
        "pr",
        "Write a pull-request description (summary + bullet points of what "
        "changed and why) for the following diff.\n\n{input}",
    ),
}

# aliases that pull `git diff` when no other input is given
GIT_ALIASES = {"c", "pr"}

_C = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "red": "\033[31m",
    "reset": "\033[0m",
}


def _c(name: str, s: str) -> str:
    return s if not sys.stdout.isatty() else f"{_C[name]}{s}{_C['reset']}"


def _user_aliases_path(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    env = os.environ.get("STENO_ALIASES")
    if env:
        return env
    default = os.path.expanduser("~/.config/steno/aliases.txt")
    return default if os.path.isfile(default) else None


def load_aliases(path: str | None = None) -> dict[str, tuple[str, str]]:
    """Built-ins merged with a user file (one `alias  template…` per line)."""
    aliases = dict(BUILTINS)
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                alias, template = parts[0], parts[1]
                if "{input}" not in template:
                    template += "\n\n{input}"
                aliases[alias] = (alias, template)
    return aliases


def expand(aliases: dict[str, tuple[str, str]], key: str, input_text: str) -> str:
    # .replace, not .format — input may contain literal braces (code!)
    return aliases[key][1].replace("{input}", input_text)


def _git_diff() -> str:
    """Staged diff if any, else the working-tree diff."""
    for args in (["diff", "--cached"], ["diff"]):
        try:
            out = subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout
        except FileNotFoundError:
            return ""
        if out.strip():
            return out
    return ""


def gather_input(rest: list[str], text_opt: str | None) -> str | None:
    """Resolve the target: --text, then file args, then literal args, then stdin."""
    if text_opt is not None:
        return text_opt
    if rest:
        if all(os.path.isfile(a) for a in rest):
            chunks = []
            for p in rest:
                with open(p, encoding="utf-8") as f:
                    chunks.append(f"// {p}\n{f.read()}")
            return "\n\n".join(chunks)
        return " ".join(rest)
    if not sys.stdin.isatty():
        try:
            data = sys.stdin.read()
        except OSError:  # e.g. stdin unavailable / captured
            data = ""
        if data.strip():
            return data
    return None


def cmd_list(aliases: dict[str, tuple[str, str]]) -> int:
    print(_c("bold", "steno aliases (two letters, and the prompt writes itself):\n"))
    for key in sorted(aliases):
        name, template = aliases[key]
        first = template.split("\n", 1)[0]
        snippet = first if len(first) <= 60 else first[:60] + "…"
        print(f"  {_c('cyan', f'{key:>4}')}  {name:<10} {_c('dim', snippet)}")
    print(_c("dim", "\n  steno <alias> <file|text>   ·   add --run to send it to Claude"))
    return 0


def run_prompt(prompt: str, model: str | None, provider: str | None = None) -> int:
    if not llm_available(provider):
        print(_c("red", llm_missing_key_message(provider)), file=sys.stderr)
        return 2
    try:
        text = llm_complete(prompt, provider=provider, model=model, max_tokens=4096)
    except LLMError as e:
        print(_c("red", f"--run failed: {e}"), file=sys.stderr)
        return 2
    print(text)
    return 0


def main(argv=None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(
        prog="steno",
        description="two letters, and the prompt writes itself.",
    )
    p.add_argument("alias", nargs="?", help="an alias, or 'ls' to list them")
    p.add_argument("rest", nargs="*", help="file(s) or free text to splice in")
    p.add_argument("--text", help="use this literal text as the input")
    p.add_argument("--run", action="store_true", help="send the prompt to an LLM")
    p.add_argument(
        "--provider",
        choices=_LLM_PROVIDERS,
        default=None,
        help="LLM provider for --run (default: auto-detect from whichever API key is set)",
    )
    p.add_argument(
        "--model",
        default=None,
        help="model id for --run (default: the provider's default, or *_MODEL / BOT_LLM_MODEL)",
    )
    p.add_argument("--aliases", help="path to a user aliases file")
    args = p.parse_args(argv)

    aliases = load_aliases(_user_aliases_path(args.aliases))

    if args.alias in (None, "ls", "list"):
        return cmd_list(aliases)

    if args.alias not in aliases:
        print(_c("red", f"unknown alias: {args.alias}"), file=sys.stderr)
        print("run `steno ls` to see them all.", file=sys.stderr)
        return 2

    input_text = gather_input(args.rest, args.text)
    if input_text is None and args.alias in GIT_ALIASES:
        input_text = _git_diff()
        if not input_text.strip():
            print(
                _c("red", "nothing to diff (no staged or working-tree changes)."), file=sys.stderr
            )
            return 2
    if input_text is None:
        print(
            _c("red", f"alias '{args.alias}' needs input — a file, text, or piped stdin."),
            file=sys.stderr,
        )
        return 2

    prompt = expand(aliases, args.alias, input_text)
    if args.run:
        return run_prompt(prompt, args.model, provider=args.provider)
    sys.stdout.write(prompt + ("\n" if not prompt.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
