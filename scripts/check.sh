#!/usr/bin/env bash
# Quality gates (constitution V, IX): lint, format, domain typing, layer contracts, tests.
set -euo pipefail
cd "$(dirname "$0")/../backend"
export PATH="$HOME/.local/bin:$PATH"
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src/automind/domain
uv run lint-imports
uv run pytest -q "$@"
if [ -d ../frontend/node_modules ]; then
  (cd ../frontend && npm run -s typecheck && npm test --silent)
fi
