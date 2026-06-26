"""Tests for frisk. Run: pytest (from repo root) or pytest frisk/"""

import json

from frisk import _load_patterns, frisk, main

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


# --- shaped PII detectors -------------------------------------------------


def test_detect_ssn():
    out, findings = frisk("ssn 123-45-6789 ok")
    assert "123-45-6789" not in out
    assert any(f["type"] == "ssn" for f in findings)


def test_detect_phone():
    out, findings = frisk("call (555) 123-4567 today")
    assert "(555) 123-4567" not in out
    assert any(f["type"] == "phone" for f in findings)


def test_credit_card_luhn_valid_is_redacted():
    out, findings = frisk("card 4111 1111 1111 1111 end")
    assert "4111 1111 1111 1111" not in out
    assert any(f["type"] == "credit_card" for f in findings)


def test_credit_card_luhn_invalid_is_left_alone():
    # Same length/shape but fails the checksum -> not a card, don't redact.
    text = "num 4111 1111 1111 1112 end"
    out, findings = frisk(text)
    assert not any(f["type"] == "credit_card" for f in findings)


# --- free-form PII via keys (opt-in) --------------------------------------


def test_pii_off_by_default():
    text = '{"name": "Ada Lovelace", "street": "12 Engine Way"}'
    out, findings = frisk(text)
    assert "Ada Lovelace" in out
    assert "12 Engine Way" in out
    assert findings == []


def test_pii_redacts_json_name_and_address():
    text = '{"name": "Ada Lovelace", "street": "12 Engine Way", "country": "UK"}'
    out, findings = frisk(text, pii=True)
    assert "Ada Lovelace" not in out
    assert "12 Engine Way" not in out
    assert '"name": "[REDACTED:name]"' in out
    assert '"street": "[REDACTED:address]"' in out
    # country is not PII-keyed -> left intact, JSON still valid.
    assert '"country": "UK"' in out
    assert {f["type"] for f in findings} == {"name", "address"}


def test_pii_normalizes_key_variants():
    out, _ = frisk('{"firstName": "Ada", "Postal_Code": "EC1A"}', pii=True)
    assert "Ada" not in out and "EC1A" not in out


def test_pii_redacts_key_value_lines():
    text = "fullName = Ada Lovelace\ncity: London\n"
    out, findings = frisk(text, pii=True)
    assert "Ada Lovelace" not in out
    assert "London" not in out
    assert {f["type"] for f in findings} == {"name", "address"}


def test_pii_offsets_round_trip():
    text = '{"name": "Ada Lovelace"}'
    _, findings = frisk(text, pii=True)
    for f in findings:
        assert text[f["start"] : f["end"]] == f["match"]


def test_pii_flag_via_main(tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text('{"name": "Ada Lovelace"}\n', encoding="utf-8")
    assert main(["--pii", str(p)]) == 0
    out = capsys.readouterr().out
    assert "Ada Lovelace" not in out
    assert "[REDACTED:name]" in out


# --- custom patterns ------------------------------------------------------


def _write_patterns(tmp_path, data):
    p = tmp_path / "patterns.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_custom_detector_redacts_custom_token(tmp_path):
    pats = _write_patterns(tmp_path, {"detectors": {"acme_key": r"ACME-[0-9]{6}"}})
    detectors, pii_keys = _load_patterns([str(pats)])
    out, findings = frisk("token=ACME-123456 ok", detectors=detectors)
    assert "ACME-123456" not in out
    assert "[REDACTED:acme_key]" in out
    assert any(f["type"] == "acme_key" for f in findings)


def test_custom_detector_runs_by_default(tmp_path):
    # No types passed -> custom detector should run like a built-in.
    pats = _write_patterns(tmp_path, {"detectors": {"acme_key": r"ACME-[0-9]{6}"}})
    detectors, _ = _load_patterns([str(pats)])
    out, findings = frisk("ACME-123456", detectors=detectors)
    assert any(f["type"] == "acme_key" for f in findings)


def test_builtins_still_work_with_custom_patterns(tmp_path):
    pats = _write_patterns(tmp_path, {"detectors": {"acme_key": r"ACME-[0-9]{6}"}})
    detectors, _ = _load_patterns([str(pats)])
    out, findings = frisk(f"aws={AWS}", detectors=detectors)
    assert AWS not in out
    assert any(f["type"] == "aws_key" for f in findings)


def test_custom_pii_key_redacts_under_pii(tmp_path):
    pats = _write_patterns(tmp_path, {"pii_keys": {"employeeId": "employee_id"}})
    _, pii_keys = _load_patterns([str(pats)])
    text = '{"employeeId": "E-4471"}'
    out, findings = frisk(text, pii=True, pii_keys=pii_keys)
    assert "E-4471" not in out
    assert "[REDACTED:employee_id]" in out
    assert any(f["type"] == "employee_id" for f in findings)


def test_custom_detector_via_main_patterns_flag(tmp_path, capsys):
    pats = _write_patterns(tmp_path, {"detectors": {"acme_key": r"ACME-[0-9]{6}"}})
    src = tmp_path / "ctx.txt"
    src.write_text("token=ACME-123456\n", encoding="utf-8")
    assert main(["--patterns", str(pats), str(src)]) == 0
    out = capsys.readouterr().out
    assert "ACME-123456" not in out
    assert "[REDACTED:acme_key]" in out


def test_custom_detector_via_env_var(tmp_path, capsys, monkeypatch):
    pats = _write_patterns(tmp_path, {"detectors": {"acme_key": r"ACME-[0-9]{6}"}})
    monkeypatch.setenv("FRISK_PATTERNS", str(pats))
    src = tmp_path / "ctx.txt"
    src.write_text("token=ACME-123456\n", encoding="utf-8")
    assert main([str(src)]) == 0
    out = capsys.readouterr().out
    assert "ACME-123456" not in out
    assert "[REDACTED:acme_key]" in out


def test_only_accepts_custom_detector(tmp_path, capsys):
    pats = _write_patterns(tmp_path, {"detectors": {"acme_key": r"ACME-[0-9]{6}"}})
    src = tmp_path / "ctx.txt"
    src.write_text("token=ACME-123456\n", encoding="utf-8")
    # --only with the custom detector must validate and apply.
    assert main(["--patterns", str(pats), "--only", "acme_key", str(src)]) == 0
    out = capsys.readouterr().out
    assert "[REDACTED:acme_key]" in out
