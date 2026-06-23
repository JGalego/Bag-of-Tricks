#!/usr/bin/env python3
"""frisk — pat it down before it ships.

Scans text headed to a model (or into logs / snitch) for secrets and PII —
API keys, tokens, private keys, JWTs, emails — and either redacts them to a
tag like ``[REDACTED:aws_key]`` or just flags them. A stdin->stdout filter:
cleaned text goes to stdout, a findings summary goes to stderr. Never prints
the full secret back at you.

    echo "key=AKIAIOSFODNN7EXAMPLE" | frisk.py
    -> key=[REDACTED:aws_key]   (summary on stderr)

    cat prompt.txt | frisk.py --check    # exit 1 if anything leaks
    frisk.py --report < context.md       # list findings, masked previews
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# --- detectors ------------------------------------------------------------
# Each entry maps a type name to a compiled regex. Order is the order they are
# tried; spans are collected across all of them and resolved left-to-right so
# overlapping matches never corrupt offsets. Patterns deliberately err toward
# well-known, high-signal shapes — we redact, we don't guess wildly.

_DETECTORS: dict[str, re.Pattern[str]] = {
    # AWS access key id: AKIA + 16 uppercase alnum.
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    # PEM private key blocks (RSA/EC/OPENSSH/DSA/PGP or bare). DOTALL: spans lines.
    "private_key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
        r".*?"
        r"-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
        re.DOTALL,
    ),
    # OpenAI-style secret keys: sk- / sk-proj- followed by a long token.
    "openai_key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    # GitHub tokens: ghp_/gho_/ghu_/ghs_/ghr_ + >=36 alnum.
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    # Slack tokens: xoxb-/xoxa-/xoxp-/xoxr-/xoxs- + the rest.
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    # Generic Authorization: Bearer <token>.
    "bearer_token": re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}"),
    # JWT: three base64url segments separated by dots (header.payload.sig).
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    # Email addresses (good-enough, not RFC-perfect).
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    # US Social Security numbers: 3-2-4 digits.
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # Credit-card-shaped runs of 13-19 digits (spaces/dashes allowed). Luhn-
    # filtered after the fact so random long numbers don't trip it.
    "credit_card": re.compile(r"\b\d(?:[ -]?\d){12,18}\b"),
    # Phone numbers: optional country code, optional (area), 3-4 split. The
    # lookarounds keep it from biting into SSNs or longer digit runs.
    "phone": re.compile(
        r"(?<![\d-])(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?![\d-])"
    ),
    # IPv4 — noisy, so only enabled when explicitly requested via --ip.
    "ipv4": re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
}

# Detectors that run by default. ipv4 is opt-in (too many false positives).
_DEFAULT_TYPES = frozenset(_DETECTORS) - {"ipv4"}

# --- free-form PII via keys ----------------------------------------------
# Names, streets, and birthdays have no reliable *shape* — so we can't regex
# them. In structured text the high-signal tell is the *key*: a field called
# "name" or "street" is almost certainly carrying PII. When pii is on we redact
# the *value* of any key that maps below, keeping the key (and the surrounding
# JSON structure) intact. Keys are normalized — lowercased, non-alphanumerics
# stripped — so "firstName", "first_name", and "First Name" all collapse to
# "firstname". The mapped label is what shows up in the redaction tag. This is
# opt-in (like ipv4): keying off field names over-redacts plain config, so the
# caller asks for it explicitly.
_PII_KEYS: dict[str, str] = {
    "name": "name", "fullname": "name", "firstname": "name", "lastname": "name",
    "middlename": "name", "givenname": "name", "surname": "name",
    "familyname": "name", "displayname": "name",
    "street": "address", "streetaddress": "address", "address": "address",
    "addressline1": "address", "addressline2": "address", "addr": "address",
    "city": "address", "state": "address", "zip": "address",
    "zipcode": "address", "postalcode": "address", "postcode": "address",
    "dob": "dob", "dateofbirth": "dob", "birthdate": "dob", "birthday": "dob",
    "phone": "phone", "phonenumber": "phone", "mobile": "phone",
    "telephone": "phone", "tel": "phone", "cell": "phone",
    "ssn": "ssn", "socialsecuritynumber": "ssn", "nationalid": "ssn",
    "passport": "passport", "passportnumber": "passport",
    "license": "license", "driverslicense": "license",
}

# A JSON string pair: "key": "value" — redacts the value's inner span only, so
# the surrounding quotes (and thus valid JSON) survive.
_PII_JSON = re.compile(r'"(?P<key>[^"]+)"\s*:\s*"(?P<val>(?:[^"\\]|\\.)*)"')

# A bare key: value / key = value line (yaml/ini/env). The value must NOT start
# with a quote, { or [ — quoted JSON values are handled by _PII_JSON, and we
# won't swallow nested structures.
_PII_LINE = re.compile(
    r"(?m)^[ \t]*(?P<key>[A-Za-z][A-Za-z0-9_. -]*?)[ \t]*[:=][ \t]*"
    r"(?P<val>[^\"{\[\n][^\n,]*?)[ \t]*,?[ \t]*$"
)


def _norm_key(key: str) -> str:
    """Lowercase a key and strip everything that isn't a letter or digit."""
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _luhn_ok(text: str) -> bool:
    """True if the digits in ``text`` pass the Luhn checksum (13-19 long)."""
    digits = [int(c) for c in text if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _pii_spans(text: str) -> list[tuple[int, int, str, str]]:
    """Spans for the *values* of PII-signalling keys (JSON + key:value lines)."""
    spans: list[tuple[int, int, str, str]] = []
    for pat in (_PII_JSON, _PII_LINE):
        for m in pat.finditer(text):
            label = _PII_KEYS.get(_norm_key(m.group("key")))
            val = m.group("val")
            if label and val.strip():
                spans.append((m.start("val"), m.end("val"), label, val))
    return spans

# How long a preview to show before the ellipsis — enough to recognize the
# shape, not enough to leak the secret.
_PREVIEW = 4


def _mask(match: str) -> str:
    """A short, non-leaking preview: first few chars + ellipsis."""
    head = match[:_PREVIEW]
    return f"{head}…" if len(match) > _PREVIEW else "…"


def frisk(
    text: str, types: set[str] | None = None, pii: bool = False
) -> tuple[str, list[dict]]:
    """Pat ``text`` down for secrets/PII.

    Returns ``(redacted_text, findings)`` where each finding is
    ``{"type", "match", "start", "end"}`` against the *original* text.
    ``types`` optionally restricts which detectors run (default: all but ipv4).
    ``pii=True`` additionally redacts free-form values (names, addresses, dates
    of birth, …) keyed off their field names — see ``_PII_KEYS``.

    Overlapping matches are resolved left-to-right, longest-first, so offsets
    stay sane and the rebuilt text never gets corrupted.
    """
    active = _DEFAULT_TYPES if types is None else (set(types) & set(_DETECTORS))

    # Collect every span from every active detector.
    spans: list[tuple[int, int, str, str]] = []
    for name in _DETECTORS:
        if name not in active:
            continue
        for m in _DETECTORS[name].finditer(text):
            # Credit-card shape is noisy; keep only Luhn-valid runs.
            if name == "credit_card" and not _luhn_ok(m.group(0)):
                continue
            spans.append((m.start(), m.end(), name, m.group(0)))

    # Free-form PII keyed off field names (opt-in).
    if pii:
        spans.extend(_pii_spans(text))

    # Sort by start, then by longest match first so we keep the widest span
    # when two detectors fire on the same region.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

    findings: list[dict] = []
    out: list[str] = []
    cursor = 0
    for start, end, name, match in spans:
        if start < cursor:
            # Overlaps an already-redacted span — skip to avoid double redaction.
            continue
        out.append(text[cursor:start])
        out.append(f"[REDACTED:{name}]")
        findings.append({"type": name, "match": match, "start": start, "end": end})
        cursor = end
    out.append(text[cursor:])

    return "".join(out), findings


def _summary_lines(findings: list[dict]) -> list[str]:
    """Human-readable, non-leaking lines for a findings list."""
    lines = []
    for f in findings:
        lines.append(f"{f['type']}\t{_mask(f['match'])}\t@{f['start']}")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="frisk",
        description="pat it down before it ships.",
    )
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument(
        "--check",
        action="store_true",
        help="don't print cleaned text; exit 1 if any secret found (gates a pipeline)",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="print findings (type + masked preview) to stdout; exit 0",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit findings as JSON (masked previews, never full secrets)",
    )
    p.add_argument(
        "--ip",
        action="store_true",
        help="also flag IPv4 addresses (off by default — too noisy)",
    )
    p.add_argument(
        "--pii",
        action="store_true",
        help="also redact free-form PII (names, addresses, DOB) keyed off field names",
    )
    p.add_argument(
        "--only",
        metavar="t1,t2",
        help="restrict to a comma-separated list of detector types",
    )
    p.add_argument(
        "--tag",
        metavar="FMT",
        default="[REDACTED:{type}]",
        help="redaction tag format, e.g. '[REDACTED:{type}]' (default)",
    )
    args = p.parse_args(argv)

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    # Resolve which detectors run.
    if args.only:
        wanted = {t.strip() for t in args.only.split(",") if t.strip()}
        unknown = wanted - set(_DETECTORS)
        if unknown:
            sys.stderr.write(
                f"[frisk] unknown detector(s): {', '.join(sorted(unknown))}\n"
                f"[frisk] known: {', '.join(sorted(_DETECTORS))}\n"
            )
            return 2
        types: set[str] | None = wanted
    else:
        types = set(_DEFAULT_TYPES)
        if args.ip:
            types.add("ipv4")

    redacted, findings = frisk(raw, types, pii=args.pii)

    # Custom tag format: rebuild from the (already correct) spans.
    if args.tag != "[REDACTED:{type}]":
        out_parts: list[str] = []
        cursor = 0
        for f in findings:
            out_parts.append(raw[cursor : f["start"]])
            out_parts.append(args.tag.format(type=f["type"]))
            cursor = f["end"]
        out_parts.append(raw[cursor:])
        redacted = "".join(out_parts)

    # --json: structured findings to stdout, nothing leaked.
    if args.json:
        payload = [
            {"type": f["type"], "preview": _mask(f["match"]), "start": f["start"], "end": f["end"]}
            for f in findings
        ]
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 1 if (args.check and findings) else 0

    # --report: list findings to stdout (masked), exit 0.
    if args.report:
        if findings:
            sys.stdout.write("\n".join(_summary_lines(findings)) + "\n")
        else:
            sys.stdout.write("clean — nothing to declare\n")
        return 0

    # Summary to stderr in every non-json mode.
    if findings:
        counts: dict[str, int] = {}
        for f in findings:
            counts[f["type"]] = counts.get(f["type"], 0) + 1
        tally = ", ".join(f"{n}×{t}" for t, n in sorted(counts.items()))
        sys.stderr.write(f"[frisk] {len(findings)} found: {tally}\n")
    else:
        sys.stderr.write("[frisk] clean\n")

    # --check: gate mode. No cleaned text, exit 1 on any finding.
    if args.check:
        return 1 if findings else 0

    # Default: print the cleaned text.
    sys.stdout.write(redacted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
