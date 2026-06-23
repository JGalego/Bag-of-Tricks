"""Tests for tell. Run: pytest (from repo root) or pytest tell/"""

from tell import main, tell


def test_stuffed_passage_scores_high():
    src = (
        "Let us delve into this rich tapestry, a testament to the realm. "
        "It is crucial and pivotal that we leverage robust, seamless systems."
    )
    result = tell(src)
    assert result["score"] >= 70
    found = {h["tell"] for h in result["hits"]}
    assert {"delve", "tapestry", "testament", "crucial"} <= found


def test_plain_technical_sentence_scores_low():
    src = "The function returns the sum of two integers and raises on overflow."
    result = tell(src)
    assert result["score"] <= 15


def test_not_just_x_its_y_detected():
    result = tell("It's not just a database, it's a platform.")
    labels = {h["tell"] for h in result["hits"]}
    assert "it's not just X, it's Y" in labels


def test_em_dashes_counted():
    result = tell("This — and that — and the other thing.")
    em = next(h for h in result["hits"] if h["tell"] == "em-dash")
    assert em["count"] == 2


def test_score_within_bounds():
    for src in ["", "delve " * 200, "a plain sentence about code.", "—" * 50]:
        s = tell(src)["score"]
        assert 0 <= s <= 100


def test_more_tells_never_lowers_score():
    base = "We leverage robust systems."
    more = "We leverage robust, seamless, crucial, pivotal systems — a testament."
    assert tell(more)["score"] >= tell(base)["score"]


def test_max_gating_exit_codes(tmp_path):
    heavy = tmp_path / "heavy.md"
    heavy.write_text(
        "Delve into this rich tapestry, a testament to the realm — crucial.",
        encoding="utf-8",
    )
    score = tell(heavy.read_text(encoding="utf-8"))["score"]
    assert score > 30  # sanity: this passage is over the gate
    assert main(["--max", "30", str(heavy)]) == 1
    assert main(["--max", "100", str(heavy)]) == 0


def test_clean_text_passes_gate(tmp_path):
    clean = tmp_path / "clean.md"
    clean.write_text("Parse the file and return a list of rows.", encoding="utf-8")
    assert main(["--max", "20", str(clean)]) == 0


def test_score_flag_only_prints_int(capsys, tmp_path):
    f = tmp_path / "x.md"
    f.write_text("delve tapestry crucial", encoding="utf-8")
    assert main(["--score", str(f)]) == 0
    out = capsys.readouterr().out.strip()
    assert out.isdigit()


def test_json_flag(capsys, tmp_path):
    import json

    f = tmp_path / "x.md"
    f.write_text("delve into the realm", encoding="utf-8")
    assert main(["--json", str(f)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {"score", "hits", "total"} <= set(data)
