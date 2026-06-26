"""Tests for bluff. Run: pytest (from repo root) or pytest bluff/

Fully offline: the network checker is stubbed everywhere via the injectable
`_checker` parameter, so no test ever opens a socket.
"""

from bluff import check_all, extract_citations, extract_urls, main


def test_extracts_bare_url():
    assert extract_urls("see https://example.com here") == ["https://example.com"]


def test_extracts_markdown_target():
    assert extract_urls("[the docs](https://example.com/docs)") == ["https://example.com/docs"]


def test_strips_trailing_period():
    assert extract_urls("read https://example.com.") == ["https://example.com"]


def test_dedupes_repeats():
    text = "https://example.com and again https://example.com"
    assert extract_urls(text) == ["https://example.com"]


def test_ignores_plain_text():
    assert extract_urls("there are no links in this sentence at all") == []


def test_markdown_and_bare_both_found_order_preserved():
    text = "first [a](https://a.example) then https://b.example done"
    assert extract_urls(text) == ["https://a.example", "https://b.example"]


def _fake_checker(results_by_url):
    def checker(url, **kwargs):
        return results_by_url[url]

    return checker


def test_check_all_reports_ok_and_dead():
    urls = ["https://ok.example", "https://dead.example"]
    fake = _fake_checker(
        {
            "https://ok.example": {
                "url": "https://ok.example",
                "ok": True,
                "status": 200,
                "error": None,
            },
            "https://dead.example": {
                "url": "https://dead.example",
                "ok": False,
                "status": 404,
                "error": "HTTP 404",
            },
        }
    )
    results = check_all(urls, _checker=fake)
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False
    assert any(not r["ok"] for r in results)  # "any dead" logic


def test_check_all_all_ok_means_none_dead():
    fake = _fake_checker(
        {
            "https://ok.example": {
                "url": "https://ok.example",
                "ok": True,
                "status": 200,
                "error": None,
            }
        }
    )
    results = check_all(["https://ok.example"], _checker=fake)
    assert all(r["ok"] for r in results)


def test_check_all_uses_injected_checker_only(monkeypatch):
    # Guard: ensure no real network is reached even if check_url existed.
    sentinel = {"url": "https://x", "ok": True, "status": 200, "error": None}
    results = check_all(["https://x"], _checker=lambda u, **k: sentinel)
    assert results == [sentinel]


def test_main_dry_run_exit_zero(tmp_path, capsys):
    f = tmp_path / "answer.md"
    f.write_text("see https://example.com and [more](https://example.org)")
    rc = main(["--dry-run", str(f)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "https://example.com" in out
    assert "https://example.org" in out


# --- custom patterns ------------------------------------------------------


def test_custom_url_pattern_surfaces_missed_link():
    # ftp:// is not matched by the built-in http(s) regexes.
    extra = {"url_patterns": [r"ftp://\S+"]}
    assert extract_urls("grab ftp://files.example/x", extra=extra) == ["ftp://files.example/x"]


def test_custom_url_pattern_with_capture_group():
    extra = {"url_patterns": [r"<(https?://[^>]+)>"]}
    assert extract_urls("see <https://example.com> here", extra=extra) == ["https://example.com"]


def test_custom_citation_pattern_surfaces_doi():
    extra = {"citation_patterns": [r"10\.\d{4,}/\S+"]}
    assert extract_citations("per doi 10.1000/xyz here", extra=extra) == ["10.1000/xyz"]


def test_no_citations_without_patterns():
    assert extract_citations("doi 10.1000/xyz", extra=None) == []


def test_default_url_extraction_unchanged_with_empty_extra():
    text = "first [a](https://a.example) then https://b.example done"
    assert extract_urls(text, extra={}) == ["https://a.example", "https://b.example"]


def test_main_dry_run_lists_custom_url_and_citation(tmp_path, capsys):
    pats = tmp_path / "pats.json"
    pats.write_text(
        '{"url_patterns": ["ftp://\\\\S+"], "citation_patterns": ["10\\\\.\\\\d{4,}/\\\\S+"]}'
    )
    f = tmp_path / "answer.md"
    f.write_text("grab ftp://files.example/x and cite 10.1000/xyz")
    rc = main(["--dry-run", "--patterns", str(pats), str(f)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ftp://files.example/x" in out
    assert "10.1000/xyz" in out


def test_main_patterns_env(tmp_path, monkeypatch, capsys):
    pats = tmp_path / "pats.json"
    pats.write_text('{"citation_patterns": ["10\\\\.\\\\d{4,}/\\\\S+"]}')
    f = tmp_path / "answer.md"
    f.write_text("cite 10.1000/xyz")
    monkeypatch.setenv("BLUFF_PATTERNS", str(pats))
    rc = main(["--dry-run", str(f)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "10.1000/xyz" in out


def test_load_patterns_merges_files(tmp_path):
    from bluff import _load_patterns

    f1 = tmp_path / "a.json"
    f1.write_text('{"url_patterns": ["ftp://\\\\S+"]}')
    f2 = tmp_path / "b.json"
    f2.write_text('{"citation_patterns": ["10\\\\.\\\\d{4,}/\\\\S+"]}')
    merged = _load_patterns([str(f1), str(f2)])
    assert merged["url_patterns"] == [r"ftp://\S+"]
    assert merged["citation_patterns"] == [r"10\.\d{4,}/\S+"]
