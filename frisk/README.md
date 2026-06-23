<p align="center">
  <img src="logo.png" alt="frisk" width="420">
</p>

You wouldn't paste your AWS key into a Slack channel. But "summarize this log
for me" quietly ships the same key to a model, a vendor, and three layers of
logging — and you'll never see it go. frisk pats the text down at the door:
secrets and PII out, everything else through.

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that tells the model to check every chunk of context for credentials before
  it forwards anything, and to redact instead of relay.
- **`frisk.py`** — a zero-dependency `stdin->stdout` filter that finds API keys,
  tokens, private keys, JWTs, emails, SSNs, credit cards, and phone numbers and
  swaps them for `[REDACTED:type]`. With `--pii` it also redacts free-form PII
  (names, addresses, DOB) keyed off field names. Cleaned text to stdout, the
  report to stderr.

## the filter

```bash
echo "key=AKIAIOSFODNN7EXAMPLE mail=joe@example.com" | python3 frisk.py
# stdout: key=[REDACTED:aws_key] mail=[REDACTED:email]
# stderr: [frisk] 2 found: 1×aws_key, 1×email

# gate a pipeline / pre-commit — exits 1 if anything leaks, prints nothing
cat staged_prompt.txt | python3 frisk.py --check && echo "clean to send"

# just list what it found, masked previews only
python3 frisk.py --report < context.md
# aws_key   AKIA…   @4
# email     joe@…   @28
```

### flags

| flag        | does                                                       |
|-------------|------------------------------------------------------------|
| *(default)* | redact to stdout, summary to stderr, exit 0                |
| `--check`   | print nothing; exit 1 if any secret found (gates pipelines)|
| `--report`  | list findings (type + masked preview) to stdout, exit 0    |
| `--json`    | emit findings as JSON (masked, never the full secret)      |
| `--ip`      | also flag IPv4 addresses (off by default — too noisy)      |
| `--pii`     | also redact free-form PII (names, addresses, DOB) by field name |
| `--only t1,t2` | restrict to listed detector types                       |
| `--tag FMT` | redaction tag format, e.g. `'<<{type}>>'`                  |

### what it looks for

AWS access keys, OpenAI keys (`sk-…`, `sk-proj-…`), GitHub tokens (`ghp_…`),
Slack tokens (`xox…`), `Bearer …` tokens, JWTs, PEM private-key blocks, email
addresses, US SSNs, credit-card numbers (Luhn-checked so random digit runs
don't trip it), and phone numbers. IPv4 is opt-in.

Free-form PII — a person's name, street, or birthday — has no regex shape, so
`--pii` keys off the *field name* instead: it redacts the value under `name`,
`street`, `city`, `dob`, `phone`, etc. (matched case- and separator-insensitively,
so `firstName` and `first_name` both count) while leaving the key and JSON
structure intact. It's opt-in because keying off field names over-redacts plain
config — reach for it on customer/user/profile data.

Findings carry their offsets, so the cleaned text round-trips byte-for-byte
around the redactions.

### what it will never do

Print the secret back at you. Summaries and reports show a masked preview only
(`AKIA…`). The whole point is to *not* be the place your key leaks next.

## install

From the repo root, [`just`](https://github.com/casey/just) symlinks the CLI
onto your `PATH` and the [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
into `~/.claude/skills/`:

```bash
just install frisk
echo "tok=ghp_0123456789abcdef0123456789abcdef0123" | frisk
```

Or run it in place: `python3 frisk.py`.

## the skill

`SKILL.md` is a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills).
`just install frisk` drops it in `~/.claude/skills/frisk/`, or copy it there
yourself. The model reads it whenever it's about to forward context that might
be carrying, and frisks it first.

## use them together

Skill at generation time (the model won't relay a key it spotted) + filter at
the boundary (anything it missed gets redacted before it ships). Pairs nicely
with [snitch](https://github.com/JGalego/Bag-of-Tricks/tree/main/snitch): frisk
what goes out, snitch on what actually went.

## not a vault

frisk is a doorman, not a security program. Regexes catch known shapes, not
every clever secret. Treat a clean pass as "no obvious leaks," not "audited."
