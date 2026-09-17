#!/usr/bin/env bash
#
# Run what CI runs, before pushing. Mirrors ci.yml next door, including its split into
# independent groups: CI has two jobs so a lint failure cannot hide a test failure, so this
# runs every check and reports them together rather than stopping at the first one.
#
# CI runs the suite on Python 3.11 and 3.13; this covers whichever interpreter is active.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

bold=$(tput bold 2>/dev/null || true)
reset=$(tput sgr0 2>/dev/null || true)
failed=""

run() {
    local name="$1"
    shift
    printf '\n%s==> %s%s\n' "$bold" "$name" "$reset"
    "$@" || failed="$failed '$name'"
}

# Recorded first, as in CI: ruff is capped to one minor line because select = ["ALL"] opts into
# every rule a new one adds, so a version mismatch is what to check when a green branch reddens.
if ! version=$(ruff --version 2>/dev/null); then
    echo "ruff not found — activate the project venv, then: pip install -e .[dev]" >&2
    exit 1
fi
echo "$version"
case "$version" in
    "ruff 0.16."*) ;;
    *) echo "${bold}warning:${reset} CI pins ruff to 0.16.x — '$version' will disagree with it" >&2 ;;
esac

run "Ruff format check" ruff format --check .
run "Ruff lint check" ruff check .
run "Tests" pytest

if [ -z "$failed" ]; then
    printf '\n%sAll CI checks passed.%s\n' "$bold" "$reset"
    exit 0
fi
printf '\n%sFailed:%s%s\n' "$bold" "$failed" "$reset"
exit 1
