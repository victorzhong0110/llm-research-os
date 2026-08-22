#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for LLM Research OS.
# Ensures the uv toolchain is present, then syncs the project's virtualenv
# (runtime + dev dependencies) from pyproject.toml / uv.lock.
set -euo pipefail

# uv installs to ~/.local/bin, which is already on PATH via the shell profile.
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found; installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

uv --version
uv sync --extra dev

echo "install complete: $(uv run python --version)"
