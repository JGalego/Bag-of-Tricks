"""Tests for mugshot. Run: pytest (from repo root) or pytest mugshot/"""

import json

from mugshot import main, mugshot

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
    rc = main(["--json", str(p)])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["verdict"] == "gpt-ish"
    assert set(parsed.keys()) == {"verdict", "confidence", "scores", "prints"}


def test_default_main_names_a_suspect(capsys, tmp_path):
    p = tmp_path / "s.txt"
    p.write_text(GPT_SAMPLE, encoding="utf-8")
    assert main([str(p)]) == 0
    out = capsys.readouterr().out
    assert "gpt-ish" in out
    assert "heuristic" in out  # honest about being a guess


def test_all_shows_scoreboard(capsys, tmp_path):
    p = tmp_path / "s.txt"
    p.write_text(GPT_SAMPLE, encoding="utf-8")
    assert main(["--all", str(p)]) == 0
    out = capsys.readouterr().out
    assert "gpt-ish" in out and "claude-ish" in out and "generic-AI" in out


def test_report_lists_prints_with_offsets(capsys, tmp_path):
    p = tmp_path / "s.txt"
    p.write_text(GPT_SAMPLE, encoding="utf-8")
    assert main(["--report", str(p)]) == 0
    out = capsys.readouterr().out
    assert "prints lifted:" in out
    assert "@" in out
