<p align="center">
  <img src="logo.png" alt="bluff" width="420">
</p>

Models cite like they mean it. Right domain, plausible path, confident tone —
and then it 404s, or the page never existed. A fluent URL is not a real one.
bluff pulls every link out of an answer and asks the only question that matters:
*does it actually resolve?*

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that tells the model to verify links before trusting them, instead of taking
  its own citations on faith.
- **`bluff.py`** — a zero-dependency CLI that extracts the URLs from any text
  and checks each one. Pipe an answer in, see what's real.

## the check

```bash
echo "See [the docs](https://example.com) and https://httpbin.org/get." \
  | python3 bluff.py
# ✓ [200] https://example.com
# ✓ [200] https://httpbin.org/get
# [bluff] 2 link(s), 0 dead

# only show the bluffs
python3 bluff.py --quiet answer.md

# structured, with a tighter timeout
python3 bluff.py --json --timeout 3 answer.md
```

Exit code is `1` if any link is dead or unreachable, `0` if they all resolve —
so it drops straight into a pre-commit hook or CI gate.

### just looking (no network)

```bash
python3 bluff.py --dry-run answer.md
# https://example.com
# https://httpbin.org/get
```

`--dry-run` extracts and lists the URLs and stops there. **Extraction is always
offline** — bare URLs and markdown `[text](url)` targets, de-duped, with
trailing sentence punctuation left out. Network is only needed to *check*.

### flags

| flag             | does                                          |
|------------------|-----------------------------------------------|
| `--dry-run`      | list URLs (and citations) only, no network    |
| `--timeout S`    | per-URL timeout in seconds (default 5)        |
| `--json`         | structured results                            |
| `-q`, `--quiet`  | print only the dead ones                      |
| `--patterns FILE`| merge custom extraction patterns (repeatable) |

### custom patterns

The built-in extraction knows bare `http(s)` URLs and markdown targets. Teach
it extra link shapes and non-URL citations with a JSON file via `--patterns
FILE` (repeatable) or the `BLUFF_PATTERNS` env var (`os.pathsep`-separated
paths, used when the flag is absent). User entries **merge with** the built-in
extraction; the built-ins stay the base.

```json
{
  "url_patterns": ["ftp://\\S+", "<(https?://[^>]+)>"],
  "citation_patterns": ["10\\.\\d{4,}/\\S+", "arXiv:\\d{4}\\.\\d+"]
}
```

- `url_patterns` are extra regexes. Each match (group 1 if the pattern has a
  capture group, else the whole match) is treated like a discovered URL and is
  **checked over the network** alongside the built-in URLs.
- `citation_patterns` match non-URL references (DOIs, arXiv ids, …). They are
  extracted and **listed but never network-checked**: in `--dry-run` they
  appear after the URLs; in check mode they report `[cited]` / ✓ with no
  request. Useful for surfacing references without pretending they're links.

```bash
python3 bluff.py --patterns mine.json --dry-run answer.md
# ftp://files.example/x
# 10.1000/xyz

BLUFF_PATTERNS=mine.json python3 bluff.py answer.md
# ✓ [200] ftp://files.example/x
# ✓ [cited] 10.1000/xyz
# [bluff] 1 link(s), 1 cited, 0 dead
```

## install

From the repo root, [`just`](https://github.com/casey/just) symlinks the CLI onto
your `PATH` and the [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
into `~/.claude/skills/`:

```bash
just install bluff
echo "https://example.com" | bluff
```

Or run it in place: `python3 bluff.py`.

## the skill

`SKILL.md` is a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills).
`just install bluff` drops it in `~/.claude/skills/bluff/`, or copy it there
yourself. The model reads it when an answer carries links worth not trusting.

## use them together

Skill at generation time (the model checks before it cites) + CLI at the
boundary (nothing dead escapes the gate). A bluff doesn't survive both.
