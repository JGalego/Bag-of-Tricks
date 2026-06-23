# bag of tricks — task runner (https://github.com/casey/just)
# `just` with no args lists recipes. Mirrors the Makefile.

# list available recipes
default:
    @just --list

# install dev/CI tooling
install:
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
