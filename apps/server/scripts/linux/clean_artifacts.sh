#!/usr/bin/env bash
set -euo pipefail

backend_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

find "$backend_root" -type d \( \
  -name "__pycache__" -o \
  -name ".ruff_cache" -o \
  -name ".mypy_cache" -o \
  -name ".pytest_cache" -o \
  -name ".cache" -o \
  -name "*.egg-info" \
\) -prune -exec rm -rf {} +

echo "Removed backend caches and editable-install metadata."
