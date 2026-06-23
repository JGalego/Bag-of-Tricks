"""Tests for frisk. Run: pytest (from repo root) or pytest frisk/"""

from frisk import frisk, main

AWS = "AKIAIOSFODNN7EXAMPLE"
SK = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
PRIV = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAabcdef\n-----END RSA PRIVATE KEY-----"


def test_detect_and_redact_aws_key():
    out, findings = frisk(f"aws={AWS}")
    assert AWS not in out
    assert "[REDACTED:aws_key]" in out
    assert findings and findings[0]["type"] == "aws_key"
    assert findings[0]["match"] == AWS


def test_detect_openai_key():
    out, findings = frisk(f"key: {SK}")
    assert SK not in out
    assert any(f["type"] == "openai_key" for f in findings)


def test_detect_private_key_block():
    out, findings = frisk(f"here:\n{PRIV}\nend")
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert any(f["type"] == "private_key" for f in findings)
    assert "[REDACTED:private_key]" in out


def test_detect_email():
    out, findings = frisk("ping joe@example.com please")
    assert "joe@example.com" not in out
    assert any(f["type"] == "email" for f in findings)


def test_clean_text_unchanged():
    text = "nothing secret here, just words and numbers 12345"
    out, findings = frisk(text)
    assert out == text
    assert findings == []


def test_only_restricts_types():
    text = f"{AWS} and joe@example.com"
    out, findings = frisk(text, types={"email"})
    assert AWS in out  # aws not requested -> untouched
    assert "joe@example.com" not in out
    assert {f["type"] for f in findings} == {"email"}


def test_redacted_output_has_no_secret():
    out, _ = frisk(f"a={AWS} b={SK}")
    assert AWS not in out
    assert SK not in out


def test_offsets_sane_with_multiple_secrets():
    text = f"first {AWS} middle joe@example.com last"
    out, findings = frisk(text)
    assert len(findings) == 2
    # Offsets point at the real spans in the original text.
    for f in findings:
        assert text[f["start"] : f["end"]] == f["match"]
    # Findings are in source order.
    assert findings[0]["start"] < findings[1]["start"]
    # Non-secret text survives the round trip.
    assert "first " in out and " middle " in out and " last" in out


def test_ipv4_off_by_default_on_by_request():
    text = "host 192.168.0.1 there"
    out_default, f_default = frisk(text)
    assert "192.168.0.1" in out_default
    assert f_default == []
    out_ip, f_ip = frisk(text, types=set(frisk.__globals__["_DEFAULT_TYPES"]) | {"ipv4"})
    assert "192.168.0.1" not in out_ip
    assert any(f["type"] == "ipv4" for f in f_ip)


def test_check_exits_1_when_secret_present(tmp_path):
    p = tmp_path / "ctx.txt"
    p.write_text(f"token={AWS}\n", encoding="utf-8")
    assert main(["--check", str(p)]) == 1


def test_check_exits_0_when_clean(tmp_path):
    p = tmp_path / "ctx.txt"
    p.write_text("all clear here\n", encoding="utf-8")
    assert main(["--check", str(p)]) == 0
