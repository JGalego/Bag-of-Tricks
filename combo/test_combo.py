"""Tests for combo. Run: pytest (from repo root) or pytest combo/

The unit tests cover parsing/resolution/gating in isolation; the integration
tests run real trick pipelines end to end through the sibling CLIs, so they
double as a smoke test that the bag still composes.
"""

import subprocess
import sys

from combo import parse_pipeline, repo_root, resolve, run_pipeline

ROOT = repo_root()


# --- parsing ---------------------------------------------------------------


def test_bare_list_is_names_only():
    assert parse_pipeline(["frisk", "launder", "deadpan"]) == [
        ["frisk"],
        ["launder"],
        ["deadpan"],
    ]


def test_pipe_string_splits_and_keeps_flags():
    assert parse_pipeline(["frisk --pii | launder | tell --score"]) == [
        ["frisk", "--pii"],
        ["launder"],
        ["tell", "--score"],
    ]


def test_pipe_string_tolerates_whitespace_and_empties():
    assert parse_pipeline(["  launder  |  | deadpan  "]) == [
        ["launder"],
        ["deadpan"],
    ]


def test_empty_pipeline():
    assert parse_pipeline([]) == []


# --- resolution ------------------------------------------------------------


def test_resolve_sibling_trick():
    prefix = resolve("launder")
    assert prefix is not None
    assert prefix[0] == sys.executable
    assert prefix[1].endswith("launder/launder.py")


def test_resolve_unknown_is_none():
    assert resolve("definitely-not-a-trick-xyz") is None


# --- gating / control flow -------------------------------------------------


def test_unknown_stage_returns_127():
    code, out = run_pipeline([["nope-not-real"]], b"hi", verbose=False)
    assert code == 127


def test_gate_aborts_routine_and_propagates_code():
    # frisk --check exits 1 on a secret and prints nothing; the second stage
    # must never run, and combo propagates the non-zero code.
    secret = b"export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIabcdEXAMPLEKEY1234567890+/x\n"
    code, out = run_pipeline([["frisk", "--check"], ["launder"]], secret, verbose=False)
    assert code == 1


def test_gate_passes_clean_input_through():
    clean = b"just plain words\n"
    code, out = run_pipeline([["frisk", "--check"], ["launder"]], clean, verbose=False)
    assert code == 0


# --- integration: real trick pipelines -------------------------------------
# Each runs the actual sibling CLIs, so it exercises the whole composition.


def run(spec, data, extra=None):
    """Invoke combo.py as a subprocess on `spec` with `data` on stdin."""
    cmd = [sys.executable, str(ROOT / "combo" / "combo.py"), *(extra or []), spec]
    return subprocess.run(cmd, input=data, capture_output=True)


def test_frisk_then_launder_redacts_and_washes():
    # A secret AND a smart quote: frisk redacts the key, launder straightens the
    # quote. Output should contain neither the raw key nor the curly quote.
    src = "token=ghp_" + "a" * 36 + " and he said “hi”\n"
    r = run("frisk | launder", src.encode())
    assert r.returncode == 0
    out = r.stdout.decode()
    assert "ghp_" + "a" * 36 not in out  # secret gone
    assert "“" not in out and "”" not in out  # quotes straightened
    assert '"hi"' in out


def test_launder_then_tell_score_is_terminal_sink():
    # filter -> analyzer: launder washes the bytes, tell --score reports a single
    # integer on the cleaned text. Final stdout is the score, not prose.
    src = (
        "Moreover, it is crucial to delve into the rich tapestry. "
        "Furthermore—and this is key—we must.\n"
    )
    r = run("launder | tell --score", src.encode())
    assert r.returncode == 0
    assert r.stdout.decode().strip().isdigit()


def test_frisk_then_salvage_redacts_inside_extracted_json():
    # filter -> filter, structured: frisk redacts a secret living inside a JSON
    # value, salvage then rips that JSON out of the surrounding chatter and
    # pretty-prints it. The secret is gone and the result parses as JSON.
    import json

    secret = "ghp_" + "a" * 36
    chatter = f'Sure! Here you go: {{"token": "{secret}", "ok": true}} — enjoy!'
    r = run("frisk | salvage", chatter.encode())
    assert r.returncode == 0
    out = r.stdout.decode()
    assert secret not in out  # redacted before extraction
    parsed = json.loads(out)  # salvage left clean, parseable JSON
    assert parsed["ok"] is True
    assert parsed["token"].startswith("[REDACTED")


def test_three_stage_clean_then_strip_personality():
    # frisk -> launder -> deadpan: redact secrets, wash bytes, strip the chirp.
    src = "Certainly! Your key is sk-" + "b" * 40 + ". I’m so happy to help—enjoy! \U0001f389\n"
    r = run("frisk | launder | deadpan", src.encode())
    assert r.returncode == 0
    out = r.stdout.decode()
    assert "sk-" + "b" * 40 not in out  # secret redacted
    assert "’" not in out and "—" not in out  # apostrophe/dash normalized
    assert "\U0001f389" not in out  # emoji stripped by deadpan


def test_bare_names_equivalent_to_quoted():
    src = "plain text he said “yo”\n"
    quoted = run("launder | deadpan", src.encode())
    bare = subprocess.run(
        [sys.executable, str(ROOT / "combo" / "combo.py"), "launder", "deadpan"],
        input=src.encode(),
        capture_output=True,
    )
    assert quoted.returncode == 0 and bare.returncode == 0
    assert quoted.stdout == bare.stdout


def test_dry_run_resolves_without_executing():
    r = run("frisk | launder | tell", b"", extra=["--dry-run"])
    assert r.returncode == 0
    text = r.stdout.decode()
    assert "routine:" in text
    assert "frisk" in text and "launder" in text and "tell" in text
    assert "UNKNOWN" not in text


def test_list_tags_shapes():
    r = subprocess.run(
        [sys.executable, str(ROOT / "combo" / "combo.py"), "--list"],
        capture_output=True,
    )
    assert r.returncode == 0
    out = r.stdout.decode()
    assert "filter" in out and "analyzer" in out
    assert "launder" in out and "tell" in out


def test_input_file_flag(tmp_path):
    p = tmp_path / "in.txt"
    p.write_text("he said “hi”\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(ROOT / "combo" / "combo.py"), "-i", str(p), "launder"],
        capture_output=True,
    )
    assert r.returncode == 0
    assert r.stdout.decode() == 'he said "hi"\n'


def test_unknown_trick_in_pipeline_errors():
    r = run("launder | totallybogustrick", b"hi\n")
    assert r.returncode == 127
    assert b"unknown trick" in r.stderr
