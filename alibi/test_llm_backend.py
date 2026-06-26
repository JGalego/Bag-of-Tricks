"""Tests for the inlined LLM backend (the `# --- llm backend ---` block).

That block is copied byte-for-byte into every trick with an --llm mode, so we
exercise it once here against alibi's copy: provider resolution, key/model
precedence, tolerant JSON parsing, and the per-provider request shaping +
response parsing for Anthropic / OpenAI / Gemini. The official SDKs are stubbed
via sys.modules — no SDK installed, no key, no network. A drift test at the
bottom asserts the block hasn't diverged across tricks.
"""

import os
import sys
import types as _t
from pathlib import Path

import pytest

import alibi as M

SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string"}},
    "required": ["verdict"],
    "additionalProperties": False,
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "BOT_LLM_PROVIDER",
        "BOT_LLM_MODEL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "GEMINI_API_KEY",
        "GEMINI_BASE_URL",
        "GEMINI_MODEL",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


# --- resolution -----------------------------------------------------------


def test_detect_prefers_anthropic_then_openai_then_gemini(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "y")
    assert M._llm_provider() == "openai"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "z")
    assert M._llm_provider() == "anthropic"


def test_forced_provider_overrides_detection(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "z")
    monkeypatch.setenv("BOT_LLM_PROVIDER", "gemini")
    assert M._llm_provider() == "gemini"


def test_provider_defaults_to_anthropic_with_no_keys():
    assert M._llm_provider() == "anthropic"


def test_google_api_key_aliases_gemini(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    assert M._llm_key("gemini") == "g"


def test_model_precedence(monkeypatch):
    assert M._llm_model("anthropic") == M._LLM_DEFAULT_MODEL["anthropic"]
    monkeypatch.setenv("ANTHROPIC_MODEL", "from-env")
    assert M._llm_model("anthropic") == "from-env"
    monkeypatch.setenv("BOT_LLM_MODEL", "from-generic")
    assert M._llm_model("anthropic") == "from-generic"
    assert M._llm_model("anthropic", "explicit") == "explicit"


def test_available_and_missing_key(monkeypatch):
    assert M.llm_available("openai") is False
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert M.llm_available("openai") is True
    assert "OPENAI_API_KEY" in M.llm_missing_key_message("openai")


def test_complete_without_key_raises():
    with pytest.raises(M.LLMError):
        M.llm_complete("hi", provider="anthropic")


def test_add_llm_args_registers_flags():
    import argparse

    p = argparse.ArgumentParser()
    M.add_llm_args(p)
    ns = p.parse_args(["--llm", "--provider", "openai", "--model", "gpt-4o"])
    assert ns.llm is True and ns.provider == "openai" and ns.model == "gpt-4o"


# --- tolerant JSON parsing ------------------------------------------------


def test_parse_json_plain_fenced_and_preamble():
    assert M._llm_parse_json('{"a": 1}') == {"a": 1}
    assert M._llm_parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert M._llm_parse_json('Sure! {"a": 1} hope that helps') == {"a": 1}


def test_parse_json_raises_when_absent():
    with pytest.raises(M.LLMError):
        M._llm_parse_json("no json here")


# --- per-provider request shaping (SDKs stubbed via sys.modules) ----------


def _install_anthropic(monkeypatch, response):
    seen = {}

    class _Client:
        def __init__(self, **kw):
            seen["client"] = kw
            self.messages = self

        def create(self, **kw):
            seen["create"] = kw
            return response

    mod = _t.ModuleType("anthropic")
    mod.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return seen


def test_anthropic_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    resp = _t.SimpleNamespace(content=[_t.SimpleNamespace(type="text", text="hello")])
    seen = _install_anthropic(monkeypatch, resp)
    assert M.llm_complete("hi", provider="anthropic", model="m") == "hello"
    assert seen["client"]["api_key"] == "k"
    assert seen["create"]["messages"][0]["content"] == "hi"


def test_anthropic_schema_uses_forced_tool(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    resp = _t.SimpleNamespace(
        content=[_t.SimpleNamespace(type="tool_use", input={"verdict": "ok"})]
    )
    seen = _install_anthropic(monkeypatch, resp)
    assert M.llm_complete("hi", provider="anthropic", schema=SCHEMA) == {"verdict": "ok"}
    assert seen["create"]["tool_choice"]["name"] == "emit"
    assert seen["create"]["tools"][0]["input_schema"] == SCHEMA


def _install_openai(monkeypatch, response, fail_on_response_format=False):
    seen = {"calls": []}

    class _Completions:
        def create(self, **kw):
            seen["calls"].append(kw)
            if fail_on_response_format and "response_format" in kw:
                raise RuntimeError("response_format unsupported")
            return response

    class _Client:
        def __init__(self, **kw):
            seen["client"] = kw
            self.chat = _t.SimpleNamespace(completions=_Completions())

    mod = _t.ModuleType("openai")
    mod.OpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", mod)
    return seen


def test_openai_text(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    resp = _t.SimpleNamespace(
        choices=[_t.SimpleNamespace(message=_t.SimpleNamespace(content="yo"))]
    )
    seen = _install_openai(monkeypatch, resp)
    assert M.llm_complete("hi", provider="openai", system="be terse") == "yo"
    assert seen["client"]["api_key"] == "k"
    assert seen["calls"][0]["messages"][0] == {"role": "system", "content": "be terse"}


def test_openai_schema_sets_response_format(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    resp = _t.SimpleNamespace(
        choices=[_t.SimpleNamespace(message=_t.SimpleNamespace(content='{"verdict": "ok"}'))]
    )
    seen = _install_openai(monkeypatch, resp)
    assert M.llm_complete("hi", provider="openai", schema=SCHEMA) == {"verdict": "ok"}
    assert seen["calls"][0]["response_format"]["type"] == "json_schema"


def test_openai_schema_falls_back_when_response_format_rejected(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    resp = _t.SimpleNamespace(
        choices=[_t.SimpleNamespace(message=_t.SimpleNamespace(content='here: {"verdict": "ok"}'))]
    )
    seen = _install_openai(monkeypatch, resp, fail_on_response_format=True)
    assert M.llm_complete("hi", provider="openai", schema=SCHEMA) == {"verdict": "ok"}
    assert len(seen["calls"]) == 2
    assert "response_format" not in seen["calls"][1]


def _install_gemini(monkeypatch, response):
    seen = {}

    class _Models:
        def generate_content(self, **kw):
            seen["generate"] = kw
            return response

    class _Client:
        def __init__(self, **kw):
            seen["client"] = kw
            self.models = _Models()

    genai = _t.ModuleType("google.genai")
    genai.Client = _Client

    types_mod = _t.ModuleType("google.genai.types")
    types_mod.HttpOptions = lambda **kw: ("http", kw)
    types_mod.GenerateContentConfig = lambda **kw: kw
    genai.types = types_mod

    google = _t.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)
    return seen


def test_gemini_text(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    resp = _t.SimpleNamespace(text="ga")
    seen = _install_gemini(monkeypatch, resp)
    assert M.llm_complete("hi", provider="gemini", model="gemini-x") == "ga"
    assert seen["client"]["api_key"] == "k"
    assert seen["generate"]["model"] == "gemini-x"


def test_gemini_schema_sets_json_mime(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    resp = _t.SimpleNamespace(text='{"verdict": "ok"}')
    seen = _install_gemini(monkeypatch, resp)
    assert M.llm_complete("hi", provider="gemini", schema=SCHEMA) == {"verdict": "ok"}
    assert seen["generate"]["config"]["response_mime_type"] == "application/json"


def test_missing_sdk_raises_llmerror(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setitem(sys.modules, "anthropic", None)  # forces ImportError
    with pytest.raises(M.LLMError):
        M.llm_complete("hi", provider="anthropic")


# --- .env loading ---------------------------------------------------------


def test_load_dotenv_sets_missing_keys_but_real_env_wins(monkeypatch, tmp_path):
    pytest.importorskip("dotenv")
    envf = tmp_path / ".env"
    envf.write_text(
        "# a comment\nexport OPENAI_API_KEY='from_dotenv'\nANTHROPIC_API_KEY=\"should_not_win\"\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)  # isolate the cwd walk from the repo's own .env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "real")  # real env already set
    monkeypatch.setenv("BOT_ENV_FILE", str(envf))
    monkeypatch.setattr(M, "_DOTENV_LOADED", False)
    try:
        M._load_dotenv()
        assert os.environ.get("OPENAI_API_KEY") == "from_dotenv"  # quotes + export stripped
        assert os.environ["ANTHROPIC_API_KEY"] == "real"  # not overridden
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        monkeypatch.setattr(M, "_DOTENV_LOADED", False)


def test_load_dotenv_runs_once(monkeypatch, tmp_path):
    pytest.importorskip("dotenv")
    envf = tmp_path / ".env"
    envf.write_text("ZZTOP_KEY=v1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_ENV_FILE", str(envf))
    monkeypatch.setattr(M, "_DOTENV_LOADED", False)
    try:
        M._load_dotenv()
        assert os.environ.get("ZZTOP_KEY") == "v1"
        envf.write_text("ZZTOP_KEY=v2\n", encoding="utf-8")
        M._load_dotenv()  # guard: second call is a no-op
        assert os.environ.get("ZZTOP_KEY") == "v1"
    finally:
        os.environ.pop("ZZTOP_KEY", None)
        monkeypatch.setattr(M, "_DOTENV_LOADED", False)


# --- drift guard ----------------------------------------------------------


def _extract_block(text):
    start = text.index("# --- llm backend")
    end = text.index("\n", text.index("# --- end llm backend")) + 1
    return text[start:end]


def test_inlined_block_is_identical_across_tricks():
    root = Path(__file__).resolve().parent.parent
    tricks = [
        "alibi",
        "mole",
        "tell",
        "fold",
        "mugshot",
        "grill",
        "strawman",
        "lineup",
        "steno",
        "interrobang",
    ]
    blocks = {}
    for t in tricks:
        src = (root / t / f"{t}.py").read_text()
        blocks[t] = _extract_block(src)
    canonical = blocks["alibi"]
    drifted = [t for t, b in blocks.items() if b != canonical]
    assert not drifted, f"llm backend block drifted from alibi in: {', '.join(drifted)}"
