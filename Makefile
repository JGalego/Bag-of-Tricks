.PHONY: help install lint fmt fmt-check test check

help:  ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## install dev/CI tooling
	pip install -r requirements-dev.txt

lint:  ## run the linter
	ruff check .

fmt:  ## auto-format the code
	ruff format .

fmt-check:  ## verify formatting without changing files
	ruff format --check .

test:  ## run the test suite
	pytest

check: lint fmt-check test  ## everything CI runs, locally
