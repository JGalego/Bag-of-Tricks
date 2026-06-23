"""Tests for alibi. Run: pytest (from repo root) or pytest alibi/"""

from alibi import alibi, main

SOURCE = (
    "The Eiffel Tower is a wrought-iron lattice tower in Paris. "
    "It is 330 metres tall and was completed in 1889."
)


def test_supported_claim_is_supported():
    results = alibi("The Eiffel Tower is 330 metres tall.", SOURCE)
    assert len(results) == 1
    assert results[0]["supported"] is True
    assert results[0]["score"] >= 0.5


def test_fabricated_claim_is_unsupported():
    results = alibi("The Eiffel Tower is painted bright orange every spring.", SOURCE)
    assert len(results) == 1
    assert results[0]["supported"] is False
    assert results[0]["score"] < 0.5


def test_mixed_answer_separates_claims():
    answer = "The Eiffel Tower is 330 metres tall. It is painted bright orange every spring."
    results = alibi(answer, SOURCE)
    assert len(results) == 2
    supported = [r for r in results if r["supported"]]
    unsupported = [r for r in results if not r["supported"]]
    assert len(supported) == 1
    assert len(unsupported) == 1
    assert "orange" in unsupported[0]["claim"]


def test_threshold_changes_the_verdict():
    # A claim with partial overlap: tune the bar around it.
    answer = "The tower in Paris was built from purple steel."
    lenient = alibi(answer, SOURCE, threshold=0.1)
    strict = alibi(answer, SOURCE, threshold=0.95)
    assert lenient[0]["supported"] is True
    assert strict[0]["supported"] is False


def test_greeting_sentence_is_neutral():
    results = alibi("Sure!", SOURCE)
    assert len(results) == 1
    # No content words to corroborate -> passes, never flagged.
    assert results[0]["supported"] is True
    assert results[0]["score"] == 1.0


def test_return_shape():
    results = alibi("Paris is the capital.", "Paris is the capital of France.")
    assert set(results[0]) == {"claim", "score", "supported"}
    assert isinstance(results[0]["supported"], bool)
    assert isinstance(results[0]["score"], float)


def test_deterministic():
    a = alibi("The Eiffel Tower is 330 metres tall.", SOURCE)
    b = alibi("The Eiffel Tower is 330 metres tall.", SOURCE)
    assert a == b


def test_check_exits_1_when_a_claim_is_unsupported(tmp_path):
    ans = tmp_path / "answer.txt"
    src = tmp_path / "source.txt"
    ans.write_text("The Eiffel Tower is painted bright orange every spring.\n", encoding="utf-8")
    src.write_text(SOURCE + "\n", encoding="utf-8")
    assert main(["--check", str(ans), "--source", str(src)]) == 1


def test_check_exits_0_when_all_claims_supported(tmp_path):
    ans = tmp_path / "answer.txt"
    src = tmp_path / "source.txt"
    ans.write_text("The Eiffel Tower is 330 metres tall.\n", encoding="utf-8")
    src.write_text(SOURCE + "\n", encoding="utf-8")
    assert main(["--check", str(ans), "--source", str(src)]) == 0


def test_main_requires_a_source(tmp_path):
    ans = tmp_path / "answer.txt"
    ans.write_text("Some claim.\n", encoding="utf-8")
    assert main([str(ans)]) == 2


def test_report_lists_unsupported(tmp_path, capsys):
    ans = tmp_path / "answer.txt"
    src = tmp_path / "source.txt"
    ans.write_text(
        "The Eiffel Tower is 330 metres tall. It is painted bright orange every spring.\n",
        encoding="utf-8",
    )
    src.write_text(SOURCE + "\n", encoding="utf-8")
    assert main(["--report", str(ans), "--source", str(src)]) == 0
    out = capsys.readouterr().out
    assert "orange" in out
    assert "330 metres" not in out


def test_source_text_flag():
    results = alibi("Paris is the capital of France.", "Paris is the capital of France.")
    assert results[0]["supported"] is True
