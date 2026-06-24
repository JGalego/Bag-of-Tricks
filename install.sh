#!/usr/bin/env bash
# bag of tricks — one-line installer
#
#   curl -fsSL https://raw.githubusercontent.com/JGalego/Bag-of-Tricks/main/install.sh | bash
#
# Downloads the repo, then for every trick symlinks its CLI into ~/.local/bin
# and its SKILL.md (+ companion .py) into ~/.claude/skills — the same wiring as
# `just install`, but with no clone and no `just` required. Discovers tricks by
# scanning the tree, so it's independent of how many are in the bag.
#
# Env knobs:
#   BOT_REPO   repo slug              (default: JGalego/Bag-of-Tricks)
#   BOT_REF    branch/tag/commit      (default: main)
#   BOT_HOME   where to keep the repo (default: ~/.bag-of-tricks)
#   BIN_DIR    where CLIs are linked  (default: ~/.local/bin)
set -euo pipefail

REPO="${BOT_REPO:-JGalego/Bag-of-Tricks}"
REF="${BOT_REF:-main}"
HOME_DIR="${BOT_HOME:-$HOME/.bag-of-tricks}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
SKILLS_DIR="${BOT_SKILLS:-$HOME/.claude/skills}"

say() { printf '  %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "curl is required"
command -v tar  >/dev/null 2>&1 || die "tar is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required to run the tricks"

printf '\n  bag of tricks — installing from %s@%s\n\n' "$REPO" "$REF"

# fetch the tree into a temp dir, then sync into HOME_DIR
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
say "downloading…"
curl -fsSL "https://github.com/$REPO/archive/refs/heads/$REF.tar.gz" \
  | tar -xz -C "$tmp" || die "download failed (check BOT_REPO / BOT_REF)"
src="$(echo "$tmp"/*/)"
[ -d "$src" ] || die "unexpected archive layout"

mkdir -p "$HOME_DIR"
# copy contents (portable: no cp -T)
( cd "$src" && tar -cf - . ) | ( cd "$HOME_DIR" && tar -xf - )

mkdir -p "$BIN_DIR" "$SKILLS_DIR"
n=0
for py in "$HOME_DIR"/*/*.py; do
  d="$(dirname "$py")"
  t="$(basename "$d")"
  # a trick is a dir whose name matches its entrypoint, e.g. frisk/frisk.py
  [ "$(basename "$py")" = "$t.py" ] || continue
  chmod +x "$py"
  ln -sf "$py" "$BIN_DIR/$t"
  if [ -f "$d/SKILL.md" ]; then
    mkdir -p "$SKILLS_DIR/$t"
    ln -sf "$d/SKILL.md" "$SKILLS_DIR/$t/SKILL.md"
    ln -sf "$py" "$SKILLS_DIR/$t/$t.py"
  fi
  say "installed $t"
  n=$((n + 1))
done
[ "$n" -gt 0 ] || die "no tricks found in the archive"

printf '\n  %d tricks installed → %s\n' "$n" "$BIN_DIR"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf '  add it to your PATH:  export PATH="%s:$PATH"\n' "$BIN_DIR" ;;
esac
printf '  skills → %s   ·   a few tricks want: pip install anthropic\n\n' "$SKILLS_DIR"
