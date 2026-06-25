# bag of tricks — task runner (https://github.com/casey/just)
# `just` with no args lists recipes.

_all := "deadpan snitch strawman interrobang steno salvage frisk tell tollbooth bluff mole launder alibi fold grill lineup mugshot squeeze combo"

# list available recipes
default:
    @just --list

# pretty-print every trick — name, catchphrase, and what it does
list:
    #!/usr/bin/env python3
    import json, textwrap
    plugins = json.load(open("{{justfile_directory()}}/.claude-plugin/marketplace.json"))["plugins"]
    BOLD, DIM, CYAN, R = "\033[1m", "\033[2m", "\033[36m", "\033[0m"
    w = max(len(p["name"]) for p in plugins)
    print(f"\n  {BOLD}bag of tricks{R} — {len(plugins)} in the bag\n")
    for p in plugins:
        tag, _, what = p["description"].partition(" — ")
        print(f"  {CYAN}{BOLD}{p['name'].ljust(w)}{R}  {tag}")
        for line in textwrap.wrap(what, 72):
            print(f"  {' ' * w}  {DIM}{line}{R}")
        print()

# install one or more tricks (default: all) as CLI commands + skills
install +tricks="all":
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{justfile_directory()}}"
    bin="${HOME}/.local/bin"
    skills="${HOME}/.claude/skills"
    want="{{tricks}}"
    [ "$want" = "all" ] && want="{{_all}}"
    for t in $want; do
      case " {{_all}} " in *" $t "*) ;; *)
        echo "unknown trick: $t (choose from: {{_all}}, or 'all')"; exit 1;; esac
      mkdir -p "$bin"
      ln -sf "$PWD/$t/$t.py" "$bin/$t"
      chmod +x "$PWD/$t/$t.py"
      echo "installed $t -> $bin/$t"
      if [ -f "$PWD/$t/SKILL.md" ]; then
        mkdir -p "$skills/$t"
        ln -sf "$PWD/$t/SKILL.md" "$skills/$t/SKILL.md"
        ln -sf "$PWD/$t/$t.py" "$skills/$t/$t.py"
        echo "  + skill -> $skills/$t/SKILL.md"
      fi
    done
    echo "make sure $bin is on your PATH (strawman also needs: pip install anthropic)."

# uninstall one or more tricks (default: all)
uninstall +tricks="all":
    #!/usr/bin/env bash
    set -euo pipefail
    bin="${HOME}/.local/bin"
    skills="${HOME}/.claude/skills"
    want="{{tricks}}"
    [ "$want" = "all" ] && want="{{_all}}"
    for t in $want; do
      rm -f "$bin/$t" "$skills/$t/SKILL.md" "$skills/$t/$t.py"
      rmdir "$skills/$t" 2>/dev/null || true
      echo "uninstalled $t"
    done

# package one or more tricks (default: all) as zips under dist/
pack +tricks="all":
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{justfile_directory()}}"
    command -v zip >/dev/null || { echo "need 'zip' installed"; exit 1; }
    mkdir -p dist
    want="{{tricks}}"
    [ "$want" = "all" ] && want="{{_all}}"
    for t in $want; do
      case " {{_all}} " in *" $t "*) ;; *)
        echo "unknown trick: $t (choose from: {{_all}}, or 'all')"; exit 1;; esac
      rm -f "dist/$t.zip"
      ( cd "$t" && zip -qr "../dist/$t.zip" . -x '*__pycache__*' '*.pyc' )
      echo "packed dist/$t.zip"
    done
    if [ "{{tricks}}" = "all" ]; then
      rm -f dist/bag-of-tricks.zip
      zip -qr dist/bag-of-tricks.zip {{_all}} README.md LICENSE -x '*__pycache__*' '*.pyc'
      echo "packed dist/bag-of-tricks.zip (whole bag)"
    fi

# open the studio — a visual, multi-branch editor for chaining tricks (PORT=8765)
studio port="8765":
    python3 "{{justfile_directory()}}/studio/server.py" --port {{port}} --open

# install dev/CI tooling (ruff + pytest + logo generation)
dev:
    pip install -r requirements-dev.txt

# (re)generate logos from source: banners, wheel, network + animation, logo
# TARGET ∈ {all banners wheel network animation web logo} (default: all).
# The full build renders the static network as category clusters and the GIF
# as the colour-ringed, node-less network (--no-category-nodes).
assets +target="all":
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{justfile_directory()}}"
    if [ "{{target}}" = "all" ]; then
      python3 assets/generate.py banners wheel network web logo
      python3 assets/generate.py animation --no-category-nodes
    else
      python3 assets/generate.py {{target}}
    fi

# run the linter
lint:
    ruff check .

# auto-format the code
fmt:
    ruff format .

# verify formatting without changing files
fmt-check:
    ruff format --check .

# run the test suite
test:
    pytest

# everything CI runs, locally
check: lint fmt-check test
