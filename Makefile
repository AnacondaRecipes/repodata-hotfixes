.PHONY: help init check lint lint-flake8 test test-hotfix test-pytest

PREFIX = $(shell conda info | grep -q 'repodata-hotfixes' || echo 'conda run -n repodata-hotfixes')

help:
	@echo 'Usage: make [COMMAND] ...'
	@echo ''
	@echo 'Commands:'
	@echo '  init         initialize development environment'
	@echo '  check        check the project for any issues (see: lint, test)'
	@echo '  lint         run all linters for the project (see: lint-flake8)'
	@echo '  lint-flake8  check source code for PEP8 compliance'
	@echo '  test         run all automated tests (see: test-pytest, test-hotfix)'
	@echo '  test-hotfix  test your repodata change'
	@echo '  test-pytest  run unit tests'

init:
	@if [ -z "$${CONDA_SHLVL:+x}" ]; then echo "Conda is not installed." && exit 1; fi
	@conda create -y -n repodata-hotfixes conda conda-index flake8 pytest requests pyyaml

check: lint test

lint: lint-flake8

lint-flake8:
	@${PREFIX} flake8 --count .

test: test-pytest test-hotfix

test-hotfix:
	@${PREFIX} python test-hotfix.py main --subdir noarch linux-32 linux-64 linux-aarch64 linux-ppc64le linux-s390x osx-64 osx-arm64 win-32 win-64

test-pytest:
	@${PREFIX} pytest -v tests/
