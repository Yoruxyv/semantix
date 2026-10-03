#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "Source this script instead:"
  echo "  source scripts/linux/enable_cache.sh"
  exit 1
fi

backend_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cache_root="$backend_root/.cache"

export PYTHONPYCACHEPREFIX="$cache_root/python"

mkdir -p \
  "$PYTHONPYCACHEPREFIX" \
  "$cache_root/ruff" \
  "$cache_root/mypy" \
  "$cache_root/pytest"

echo "Backend caches are centralized under $cache_root"
echo "PYTHONPYCACHEPREFIX=$PYTHONPYCACHEPREFIX"
