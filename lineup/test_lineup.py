"""Tests for lineup. Run: pytest (from repo root) or pytest lineup/

The real run() calls the Anthropic API; these tests stub the `anthropic`
module so no key or network is needed. Everything here runs offline.
"""

import sys
import types

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
    # No anthropic import should happen on the --dry-run path.
    assert lineup.main(["--prompt", "hello", "--dry-run"]) == 0


def test_main_dry_run_does_not_import_anthropic(monkeypatch):
    # Ensure the dry-run path never touches the SDK: if it tries, the import
    # would fail because we set the module to None.
    monkeypatch.setitem(sys.modules, "anthropic", None)
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


def _fake_anthropic(answers_by_model: dict):
    """Build a stand-in `anthropic` module whose client echoes per-model text."""

    class _Block:
        type = "text"

        def __init__(self, t):
            self.text = t

    class _Usage:
        input_tokens = 5
        output_tokens = 7

    class _Resp:
        def __init__(self, text):
            self.content = [_Block(text)]
            self.usage = _Usage()

    class _Messages:
        def create(self, **kwargs):
            model = kwargs["model"]
            return _Resp(answers_by_model.get(model, f"answer from {model}"))

    class _Client:
        messages = _Messages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = lambda *a, **k: _Client()
    return mod


def test_run_labels_each_model(monkeypatch, capsys):
    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        _fake_anthropic({"m1": "first answer", "m2": "second answer"}),
    )
    rc = lineup.run("the prompt", ["m1", "m2"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "m1" in out and "m2" in out
    assert "first answer" in out and "second answer" in out
    assert "2/2 answered" in out


def test_run_missing_sdk_returns_2(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    assert lineup.run("prompt", ["m1"]) == 2
