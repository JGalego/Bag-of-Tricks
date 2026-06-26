"""Tests for mugshot. Run: pytest (from repo root) or pytest mugshot/"""

import json

import mugshot as mugshot_mod
from mugshot import main, mugshot, mugshot_llm

GPT_SAMPLE = (
    "Certainly! I'd be happy to help. It's important to note that we should "
    "approach this carefully.\n"
    "1. First, gather the facts.\n"
    "2. Then, weigh the options.\n"
    "In conclusion, the plan is sound. I hope this helps!"
)

NEUTRAL = "The cat sat on the mat and then it went outside to look at the rain."


def test_gpt_sample_ranks_gpt_ish_on_top():
    result = mugshot(GPT_SAMPLE)
    assert result["verdict"] == "gpt-ish"
    # gpt-ish should out-score every other suspect.
    scores = result["scores"]
    top = scores["gpt-ish"]
    assert all(top >= v for v in scores.values())
    assert result["confidence"] in {"low", "medium", "high"}


def test_neutral_text_is_inconclusive():
    result = mugshot(NEUTRAL)
    assert result["verdict"] == "human / inconclusive"
    assert result["confidence"] == "low"


def test_return_dict_shape():
    result = mugshot(GPT_SAMPLE)
    assert set(result.keys()) == {"verdict", "confidence", "scores", "prints"}
    assert isinstance(result["verdict"], str)
    assert result["confidence"] in {"low", "medium", "high"}
    assert set(result["scores"].keys()) == {"gpt-ish", "claude-ish", "generic-AI"}
    for p in result["prints"]:
        assert set(p.keys()) == {"suspect", "match", "label", "start", "weight"}
        # Offsets point at the real matched span.
        assert GPT_SAMPLE[p["start"] : p["start"] + len(p["match"])] == p["match"]


def test_prints_are_in_offset_order():
    result = mugshot(GPT_SAMPLE)
    offsets = [p["start"] for p in result["prints"]]
    assert offsets == sorted(offsets)


def test_ranking_is_deterministic():
    a = mugshot(GPT_SAMPLE)
    b = mugshot(GPT_SAMPLE)
    assert a == b


def test_claude_sample_ranks_claude_ish():
    text = "Great question! Let me walk you through it.\nHere's the gist — it's quick."
    result = mugshot(text)
    assert result["verdict"] == "claude-ish"


def test_generic_ai_tells_detected():
    text = "Let's delve into the rich tapestry — a testament to our ever-evolving craft."
    result = mugshot(text)
    assert result["scores"]["generic-AI"] > 0
    assert any(p["suspect"] == "generic-AI" for p in result["prints"])


def test_json_via_main_emits_valid_json(tmp_path, capsys):
    p = tmp_path / "sample.txt"
    p.write_text(GPT_SAMPLE, encoding="utf-8")
    rc = main(["--parlor", "--json", str(p)])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["verdict"] == "gpt-ish"
    assert set(parsed.keys()) == {"verdict", "confidence", "scores", "prints"}


def test_default_main_names_a_suspect(capsys, tmp_path, monkeypatch):
    # No key configured -> default falls back to the offline parlor heuristic.
    monkeypatch.setattr(mugshot_mod, "llm_available", lambda provider=None: False)
    p = tmp_path / "s.txt"
    p.write_text(GPT_SAMPLE, encoding="utf-8")
    assert main([str(p)]) == 0
    out = capsys.readouterr().out
    assert "gpt-ish" in out
    assert "heuristic" in out  # honest about being a guess


def test_all_shows_scoreboard(capsys, tmp_path):
    p = tmp_path / "s.txt"
    p.write_text(GPT_SAMPLE, encoding="utf-8")
    assert main(["--parlor", "--all", str(p)]) == 0
    out = capsys.readouterr().out
    assert "gpt-ish" in out and "claude-ish" in out and "generic-AI" in out


def test_report_lists_prints_with_offsets(capsys, tmp_path):
    p = tmp_path / "s.txt"
    p.write_text(GPT_SAMPLE, encoding="utf-8")
    assert main(["--parlor", "--report", str(p)]) == 0
    out = capsys.readouterr().out
    assert "prints lifted:" in out
    assert "@" in out


# --- model-backed path: stub the network seam, never call out ----------------


def _stub_complete(monkeypatch, payload):
    """Make mugshot_llm's model return the given structured verdict."""

    def fake_complete(prompt, **kwargs):
        return payload

    monkeypatch.setattr(mugshot_mod, "llm_complete", fake_complete)


_LLM_PAYLOAD = {
    "verdict": "gpt/openai",
    "confidence": "high",
    "scores": [
        {"family": "gpt/openai", "score": 0.8},
        {"family": "claude/anthropic", "score": 0.1},
        {"family": "human / inconclusive", "score": 0.1},
    ],
    "prints": [
        {"suspect": "gpt/openai", "match": "Certainly!", "label": "opener"},
        {"suspect": "gpt/openai", "match": "In conclusion", "label": "windup"},
    ],
}


def test_llm_path_returns_mugshot_shape(monkeypatch):
    _stub_complete(monkeypatch, _LLM_PAYLOAD)
    result = mugshot_llm(GPT_SAMPLE)
    assert set(result.keys()) == {"verdict", "confidence", "scores", "prints"}
    assert result["verdict"] == "gpt/openai"
    assert result["confidence"] == "high"
    assert result["scores"]["gpt/openai"] == 0.8
    for p in result["prints"]:
        assert set(p.keys()) == {"suspect", "match", "label", "start", "weight"}
    # 'Certainly!' is locatable in the sample, so its offset points at the span.
    cert = next(p for p in result["prints"] if p["match"] == "Certainly!")
    assert GPT_SAMPLE[cert["start"] : cert["start"] + len(cert["match"])] == "Certainly!"


def test_llm_path_missing_match_gets_offset_minus_one(monkeypatch):
    payload = dict(_LLM_PAYLOAD)
    payload["prints"] = [{"suspect": "gpt/openai", "match": "not in the text", "label": "x"}]
    _stub_complete(monkeypatch, payload)
    result = mugshot_llm(GPT_SAMPLE)
    assert result["prints"][0]["start"] == -1
    assert result["prints"][0]["weight"] == 1.0


def test_main_llm_flag_routes_to_model(monkeypatch, tmp_path, capsys):
    _stub_complete(monkeypatch, _LLM_PAYLOAD)
    p = tmp_path / "s.txt"
    p.write_text(GPT_SAMPLE, encoding="utf-8")
    assert main(["--llm", "--json", str(p)]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["verdict"] == "gpt/openai"


def test_main_llm_failure_returns_2(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise mugshot_mod.LLMError("no key")

    monkeypatch.setattr(mugshot_mod, "llm_complete", boom)
    p = tmp_path / "s.txt"
    p.write_text(GPT_SAMPLE, encoding="utf-8")
    assert main(["--llm", str(p)]) == 2


def test_main_default_uses_model_when_key_available(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(mugshot_mod, "llm_available", lambda provider=None: True)
    _stub_complete(monkeypatch, _LLM_PAYLOAD)
    p = tmp_path / "s.txt"
    p.write_text(GPT_SAMPLE, encoding="utf-8")
    assert main(["--json", str(p)]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["verdict"] == "gpt/openai"


def test_parlor_flag_forces_regex_even_with_key(monkeypatch, tmp_path, capsys):
    # A key is available, but --parlor must still use the offline heuristic and
    # never touch the model seam.
    monkeypatch.setattr(mugshot_mod, "llm_available", lambda provider=None: True)

    def boom(*a, **k):
        raise AssertionError("model should not be called in --parlor mode")

    monkeypatch.setattr(mugshot_mod, "llm_complete", boom)
    p = tmp_path / "s.txt"
    p.write_text(GPT_SAMPLE, encoding="utf-8")
    assert main(["--parlor", "--json", str(p)]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["verdict"] == "gpt-ish"


def test_default_falls_back_to_parlor_without_key(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(mugshot_mod, "llm_available", lambda provider=None: False)
    p = tmp_path / "s.txt"
    p.write_text(GPT_SAMPLE, encoding="utf-8")
    assert main(["--json", str(p)]) == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["verdict"] == "gpt-ish"
    # The note steering the user toward real attribution lands on stderr.
    assert "offline" in captured.err and "API key" in captured.err


# --- custom patterns ---------------------------------------------------------


def test_custom_patterns_merge_creates_new_suspect(tmp_path, capsys):
    pat = tmp_path / "extra.json"
    pat.write_text(
        json.dumps({"suspects": {"robot-ish": [[5.0, "beep boop", r"\bbeep boop\b"]]}}),
        encoding="utf-8",
    )
    src = tmp_path / "s.txt"
    src.write_text("beep boop beep boop beep boop", encoding="utf-8")
    assert main(["--parlor", "--patterns", str(pat), "--json", str(src)]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["verdict"] == "robot-ish"
    assert "robot-ish" in parsed["scores"]


def test_custom_patterns_via_env(tmp_path, capsys, monkeypatch):
    pat = tmp_path / "extra.json"
    pat.write_text(
        json.dumps({"suspects": {"robot-ish": [[5.0, "beep", r"\bbeep\b"]]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MUGSHOT_PATTERNS", str(pat))
    src = tmp_path / "s.txt"
    src.write_text("beep beep beep beep", encoding="utf-8")
    assert main(["--parlor", "--json", str(src)]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert "robot-ish" in parsed["scores"]
