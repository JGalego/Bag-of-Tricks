"""Tests for lineup. Run: pytest (from repo root) or pytest lineup/

The real run() calls the shared multi-provider helper; these tests stub
`lineup.llm_complete` so no key or network is needed. Everything here
runs offline.
"""

import lineup


def test_parse_models_splits_and_strips():
    assert lineup.parse_models("a,b,c") == ["a", "b", "c"]
    assert lineup.parse_models(" a , b ,c ") == ["a", "b", "c"]


def test_parse_models_drops_empties():
    assert lineup.parse_models("a,,b,") == ["a", "b"]
    assert lineup.parse_models("") == []


def test_default_models_non_empty():
    assert lineup.DEFAULT_MODELS
    assert all(isinstance(m, str) and m for m in lineup.DEFAULT_MODELS)


def test_plan_lists_each_model_and_prompt():
    out = lineup.plan("Explain TCP in one sentence.", ["m1", "m2", "m3"])
    assert "Explain TCP in one sentence." in out
    for m in ("m1", "m2", "m3"):
        assert m in out


def test_plan_truncates_long_prompt():
    out = lineup.plan("x" * 1000, ["m1"])
    assert "..." in out
    assert "x" * 1000 not in out


def test_dry_run_returns_zero_and_shows_plan(capsys):
    rc = lineup.dry_run("hi there", ["m1", "m2"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "hi there" in out
    assert "m1" in out and "m2" in out


def test_main_dry_run_returns_zero_offline():
    # The --dry-run path never calls the helper.
    assert lineup.main(["--prompt", "hello", "--dry-run"]) == 0


def test_main_dry_run_does_not_call_complete(monkeypatch):
    # Ensure the dry-run path never touches the LLM helper: if it tries, this
    # stub raises and the test fails.
    def _boom(*a, **k):
        raise AssertionError("complete() should not be called on --dry-run")

    monkeypatch.setattr(lineup, "llm_complete", _boom)
    assert lineup.main(["--prompt", "hello", "--models", "a,b", "--dry-run"]) == 0


def test_main_dry_run_with_custom_models(capsys):
    rc = lineup.main(["--prompt", "q", "--models", "x,y,z", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    for m in ("x", "y", "z"):
        assert m in out


def test_main_empty_prompt_returns_2():
    assert lineup.main(["--prompt", "   ", "--dry-run"]) == 2


def test_main_no_models_returns_2():
    assert lineup.main(["--prompt", "q", "--models", " , ", "--dry-run"]) == 2


def _stub_complete(answers_by_model: dict):
    """A stand-in for `llm_complete` that echoes per-model text."""

    def _complete(prompt, **kwargs):
        model = kwargs.get("model")
        return answers_by_model.get(model, f"answer from {model}")

    return _complete


def test_provider_for_prefix_inference():
    assert lineup.provider_for("claude-opus-4-8") == ("anthropic", "claude-opus-4-8")
    assert lineup.provider_for("anthropic-foo") == ("anthropic", "anthropic-foo")
    assert lineup.provider_for("gpt-4o") == ("openai", "gpt-4o")
    assert lineup.provider_for("o1-mini") == ("openai", "o1-mini")
    assert lineup.provider_for("o3") == ("openai", "o3")
    assert lineup.provider_for("chatgpt-4o-latest") == ("openai", "chatgpt-4o-latest")
    assert lineup.provider_for("gemini-2.5-flash") == ("gemini", "gemini-2.5-flash")
    assert lineup.provider_for("models/gemini-pro") == ("gemini", "models/gemini-pro")
    # unknown prefix falls back to the default (None for auto)
    assert lineup.provider_for("mystery-model") == (None, "mystery-model")
    assert lineup.provider_for("mystery-model", "openai") == ("openai", "mystery-model")


def test_provider_for_explicit_syntax():
    assert lineup.provider_for("openai:gpt-4o") == ("openai", "gpt-4o")
    assert lineup.provider_for("anthropic:claude-haiku-4-5") == (
        "anthropic",
        "claude-haiku-4-5",
    )
    assert lineup.provider_for("gemini:models/gemini-pro") == ("gemini", "models/gemini-pro")
    # an unknown provider prefix is not treated as a provider split
    assert lineup.provider_for("foo:bar", "openai") == ("openai", "foo:bar")


def test_run_labels_each_model(monkeypatch, capsys):
    monkeypatch.setattr(
        lineup,
        "llm_complete",
        _stub_complete({"m1": "first answer", "m2": "second answer"}),
    )
    rc = lineup.run("the prompt", ["m1", "m2"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "m1" in out and "m2" in out
    assert "first answer" in out and "second answer" in out
    assert "2/2 answered" in out


def test_run_all_errored_returns_1(monkeypatch, capsys):
    def _always_fail(prompt, **kwargs):
        raise lineup.LLMError("nope")

    monkeypatch.setattr(lineup, "llm_complete", _always_fail)
    rc = lineup.run("prompt", ["m1", "m2"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "0/2 answered" in out
