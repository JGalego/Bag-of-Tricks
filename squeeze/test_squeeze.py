"""Tests for squeeze. Run: pytest (from repo root) or pytest squeeze/"""

import json

from squeeze import AI_CORPUS, HUMAN_CORPUS, main, squeeze

AI_SAMPLE = (
    "Certainly! I'd be happy to help. It's important to note that we should "
    "delve into this rich tapestry. In today's fast-paced world, it is crucial "
    "to leverage robust, seamless solutions. In conclusion, this serves as a "
    "testament to the ever-evolving landscape of innovation. I hope this helps!"
)

HUMAN_SAMPLE = (
    "ok so the build broke again, no idea why. spent an hour on it, turned out "
    "Dave renamed the flag and didn't tell anyone, classic. fixed it, grabbed "
    "coffee, the machine was out of beans of course. pushed the fix anyway, "
    "fingers crossed it sticks this time."
)


def test_ai_sample_leans_ai():
    r = squeeze(AI_SAMPLE)
    assert r["verdict"] == "likely AI-generated"
    assert r["ai_ncd"] < r["human_ncd"]
    assert r["margin"] > 0
    assert r["ai_likelihood"] >= 50


def test_human_sample_leans_human():
    r = squeeze(HUMAN_SAMPLE)
    assert r["verdict"] == "likely human-written"
    assert r["human_ncd"] < r["ai_ncd"]
    assert r["margin"] < 0
    assert r["ai_likelihood"] <= 50


def test_return_dict_shape():
    r = squeeze(AI_SAMPLE)
    assert set(r.keys()) == {
        "verdict",
        "confidence",
        "ai_likelihood",
        "ai_ncd",
        "human_ncd",
        "margin",
        "algo",
        "words",
        "chunks",
    }
    assert r["verdict"] in {
        "likely AI-generated",
        "likely human-written",
        "inconclusive",
    }
    assert r["confidence"] in {"low", "medium", "high"}
    assert 0 <= r["ai_likelihood"] <= 100


def test_short_text_is_low_confidence():
    r = squeeze("The cat sat on the mat.")
    assert r["confidence"] == "low"


def test_short_text_is_one_chunk():
    assert squeeze(AI_SAMPLE)["chunks"] == 1


def test_long_input_is_chunked_and_aggregates():
    # A long AI-slop blob must split into many windows yet still read as AI —
    # chunking must not let the bulk swamp the small corpus into a 1.0 tie.
    blob = (AI_SAMPLE + "\n\n") * 40
    r = squeeze(blob, chunk=2000)
    assert r["chunks"] > 1
    assert r["verdict"] == "likely AI-generated"
    assert r["ai_ncd"] < 1.0 and r["human_ncd"] < 1.0  # no saturation


def test_chunk_size_controls_window_count():
    blob = (HUMAN_SAMPLE + "\n\n") * 20
    big = squeeze(blob, chunk=100_000)["chunks"]
    small = squeeze(blob, chunk=500)["chunks"]
    assert big == 1
    assert small > big


def test_identical_corpus_is_inconclusive_or_decisive_but_consistent():
    # Feeding the AI corpus back to itself must read as maximally AI-leaning.
    r = squeeze(AI_CORPUS)
    assert r["ai_ncd"] < r["human_ncd"]
    assert r["verdict"] == "likely AI-generated"


def test_all_algos_agree_on_direction():
    for algo in ("lzma", "zlib", "bz2"):
        r = squeeze(AI_SAMPLE, algo=algo)
        assert r["margin"] > 0, f"{algo} should lean AI on the AI sample"
        assert r["algo"] == algo


def test_custom_corpora_flip_the_verdict():
    # Swap the corpora: the AI sample should now read as "human".
    r = squeeze(AI_SAMPLE, ai_corpus=HUMAN_CORPUS, human_corpus=AI_CORPUS)
    assert r["verdict"] == "likely human-written"


def test_json_output(capsys, tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text(AI_SAMPLE, encoding="utf-8")
    rc = main([str(f), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    json.loads(out)  # must be parseable JSON


def test_max_gate_trips_on_ai(tmp_path):
    f = tmp_path / "ai.txt"
    f.write_text(AI_SAMPLE, encoding="utf-8")
    assert main([str(f), "--max", "40"]) == 1  # AI text exceeds the gate
    assert main([str(f), "--max", "100"]) == 0  # nothing exceeds 100
