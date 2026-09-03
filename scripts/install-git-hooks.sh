#!/bin/sh
# Point this clone at the repository hooks. Git does not honour a committed
# core.hooksPath; this script is the one-shot local setup (see
# docs/engineering-standards.md). CI still rejects agent Co-authored-by
# trailers even when the hook is not installed.
set -eu
root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
git -C "$root" config core.hooksPath scripts/git-hooks
echo "core.hooksPath=$(git -C "$root" config --get core.hooksPath)"
