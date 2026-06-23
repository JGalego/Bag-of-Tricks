"""Tests for tollbooth. These exercise the heuristic path and do NOT require tiktoken."""

from __future__ import annotations

import pytest

from tollbooth import PRICES, cost, count_tokens, main


def test_empty_string_is_zero():
    assert count_tokens("") == 0


def test_normal_sentence_is_positive_int():
    n = count_tokens("The quick brown fox jumps over the lazy dog.")
    assert isinstance(n, int)
    assert n > 0


def test_monotonic_longer_is_not_fewer():
    short = "hello world"
    long = short + " " + ("more text here " * 50)
    assert count_tokens(long) >= count_tokens(short)
    # Appending never lowers the count.
    growing = ""
    prev = 0
    for chunk in ["a ", "bb ", "ccc ", "dddd "] * 5:
        growing += chunk
        cur = count_tokens(growing)
        assert cur >= prev
        prev = cur


def test_cost_math_input_only():
    # 1M input tokens at the table's "in" rate equals exactly that rate.
    model = "claude-sonnet-4-6"
    result = cost(model, 1_000_000)
    assert result["input_usd"] == pytest.approx(PRICES[model]["in"])
    assert result["output_usd"] == 0.0
    assert result["total_usd"] == pytest.approx(PRICES[model]["in"])


def test_cost_math_output_adds():
    model = "claude-opus-4-8"
    result = cost(model, 1_000_000, 1_000_000)
    assert result["input_usd"] == pytest.approx(PRICES[model]["in"])
    assert result["output_usd"] == pytest.approx(PRICES[model]["out"])
    assert result["total_usd"] == pytest.approx(PRICES[model]["in"] + PRICES[model]["out"])


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        cost("does-not-exist", 100)


def test_list_models_returns_zero():
    assert main(["--list-models"]) == 0


def test_tokens_only_prints_number(tmp_path, capsys):
    f = tmp_path / "prompt.txt"
    f.write_text("The quick brown fox jumps over the lazy dog.")
    rc = main([str(f), "--tokens-only"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.isdigit()
    assert int(out) > 0
