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
    echo "make sure $bin is on your PATH (--llm modes need one provider SDK: pip install anthropic | openai | google-genai)."

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

# Bump the version, commit, tag, and push — CI builds the GitHub Release from
# the tag (see .github/workflows/release.yml). The version arg is optional and
# defaults to a patch bump of whatever the manifest currently says; pass
# major|minor to bump that segment, or an explicit N.N.N to set it outright.
#   just release frisk         ->  0.1.0 -> 0.1.1, tags frisk-v0.1.1
#   just release frisk minor   ->  0.1.0 -> 0.2.0, tags frisk-v0.2.0
#   just release all 1.0.0     ->  sets the bag to v1.0.0

# cut a release & push the tag — `just release <trick|all> [major|minor|patch|N.N.N]`
release trick version="patch":
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{justfile_directory()}}"
    trick="{{trick}}"
    bump="{{version}}"
    # locate the manifest + read its current version (the source of truth)
    if [ "$trick" = "all" ]; then
      manifest="pyproject.toml"
      current="$(python3 -c "import re;print(re.search(r'^version = \"([^\"]+)\"', open('pyproject.toml').read(), re.M).group(1))")"
    else
      case " {{_all}} " in *" $trick "*) ;; *)
        echo "unknown trick: $trick (choose from: {{_all}}, or 'all')"; exit 1;; esac
      manifest="$trick/.claude-plugin/plugin.json"
      current="$(python3 -c "import json;print(json.load(open('$manifest'))['version'])")"
    fi
    # resolve the target version: a major|minor|patch bump of current, or N.N.N
    core="${current%%-*}"                  # drop any -rc/-beta suffix before bumping
    IFS=. read -r MA MI PA _ <<< "$core"
    : "${MA:=0}" "${MI:=0}" "${PA:=0}"
    case "$bump" in
      major) version="$((MA + 1)).0.0" ;;
      minor) version="$MA.$((MI + 1)).0" ;;
      patch) version="$MA.$MI.$((PA + 1))" ;;
      *)
        version="${bump#v}"
        [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-].+)?$ ]] \
          || { echo "bad version: '$bump' (want N.N.N, a -rc1/-beta suffix, or major|minor|patch)"; exit 1; } ;;
    esac
    [ "$trick" = "all" ] && tag="v$version" || tag="$trick-v$version"
    echo "$trick: $current -> $version  (tag $tag)"
    [ "$current" = "$version" ] && { echo "already at $version in $manifest — nothing to bump"; exit 1; }
    # clean tree so the release commit is just the version bump
    git diff --quiet && git diff --cached --quiet \
      || { echo "working tree not clean — commit or stash first"; exit 1; }
    # 1/ confirm before writing the new version
    read -r -p "set $manifest to $version, commit, and tag $tag? [y/N] " ans || true
    [[ "$ans" =~ ^[Yy] ]] || { echo "aborted — nothing changed."; exit 1; }
    if [ "$trick" = "all" ]; then
      sed -i -E "s/^version = \"[^\"]+\"/version = \"$version\"/" "$manifest"
    else
      sed -i -E "s/(\"version\"[[:space:]]*:[[:space:]]*\")[^\"]+\"/\1$version\"/" "$manifest"
    fi
    git add "$manifest"
    git commit -m "release($trick): $tag"
    git tag -a "$tag" -m "$tag"
    # 2/ confirm before pushing (the push is what triggers the release workflow)
    read -r -p "push commit + $tag to origin? this kicks off the release [y/N] " ans || true
    if [[ "$ans" =~ ^[Yy] ]]; then
      git push origin HEAD "$tag"
      echo "pushed $tag — watch the release at: gh run watch  (or the Actions tab)"
    else
      echo "not pushed. local commit + tag $tag are ready; push when you are:"
      echo "  git push origin HEAD $tag"
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
