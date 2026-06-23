# bag of tricks — task runner (https://github.com/casey/just)
# `just` with no args lists recipes.

_all := "deadpan snitch strawman interrobang"

# list available recipes
default:
    @just --list

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
      rm -f "$bin/$t" "$skills/$t/SKILL.md"
      rmdir "$skills/$t" 2>/dev/null || true
      echo "uninstalled $t"
    done

# install dev/CI tooling (ruff + pytest)
dev:
    pip install -r requirements-dev.txt

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
