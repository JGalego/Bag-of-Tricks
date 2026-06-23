<p align="center">
  <img src="logo.png" alt="deadpan" width="420">
</p>

Caveman makes the model *short*. deadpan makes it *shut up*. A response can be
terse and still chirpy — "Sure! 42 🎉" is four tokens of personality wrapped
around one token of answer. deadpan removes the *manner*, never the *matter*.

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that tells the model to stop performing. Drop it in and the model answers like
  a person who's busy.
- **`deadpan.py`** — a zero-dependency post-filter that strips personality out of
  text that *already exists* (your model's, someone else's, a docstring, a
  changelog). Pipe anything through it.

## the filter

```bash
echo "Certainly! I'd be happy to help. The answer is 42 🎉 Hope this helps!" \
  | python3 deadpan.py
# -> The answer is 42

# files, with a quietness report
python3 deadpan.py --level ultra response.md --stats
# ...output...
# [deadpan] 1840 -> 1102 chars  (738 cut, 40% quieter)
```

### levels

| level   | drops                                              | keeps |
|---------|---------------------------------------------------|-------|
| `lite`  | openers, sign-offs, "as an AI…", sycophancy       | emoji, hedges |
| `full`  | + emoji, + hedges ("I think", "basically", "just")| structure |
| `ultra` | + collapses runaway whitespace                    | the answer |

Default is `full`.

### what it will never touch

Code fences (```` ``` ````, `~~~`) and inline `` `code` `` pass through byte for
byte. deadpan trims the prose *around* your snippets, never the snippets.

## install

From the repo root, [`just`](https://github.com/casey/just) symlinks the CLI onto
your `PATH` and the [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
into `~/.claude/skills/`:

```bash
just install deadpan
echo "Sure! 42 🎉" | deadpan
```

Or run it in place: `python3 deadpan.py`.

## the skill

`SKILL.md` is a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills).
`just install deadpan` drops it in `~/.claude/skills/deadpan/`, or copy it there
yourself. The model reads it when terse, direct output is wanted and stops
opening with "Certainly!".

## use them together

Skill at generation time (no fluff produced) + filter at the boundary (no fluff
escapes). Belt and suspenders for people who can't stand "I hope this helps!".

## not a muzzle

deadpan is plain, not hostile. It keeps every fact, caveat, and step that
changes what you do next. If you want *shorter*, that's [caveman](https://github.com/juliusbrussee/caveman)'s
job — deadpan is about *quieter*.
