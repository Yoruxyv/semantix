#!/usr/bin/env bash
set -euo pipefail

compose=(
  docker compose
  -f docker-compose.dev.yml
  -f ops/ci/docker-compose.dev-smoke.yml
)
backend_port="${BACKEND_PORT:-8000}"
python_command="${PYTHON_COMMAND:-python3}"

cleanup() {
  "${compose[@]}" --profile pgvector down --volumes --remove-orphans
}
trap cleanup EXIT

generate_secret() {
  "$python_command" -c 'import secrets; print(secrets.token_urlsafe(32))'
}

export EMBEDDING_PROVIDER=mock
export GENERATION_PROVIDER=mock
export CACHE_BACKEND=memory

"${compose[@]}" up --build --detach --wait --wait-timeout 180
curl --fail --silent --show-error "http://127.0.0.1:${backend_port}/health"
"${compose[@]}" down --volumes --remove-orphans

export CACHE_BACKEND=pgvector
export POSTGRES_USER="${POSTGRES_USER:-semantix}"
export POSTGRES_DB="${POSTGRES_DB:-semantix}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(generate_secret)}"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"

"${compose[@]}" --profile pgvector up --no-build --detach --wait --wait-timeout 180
curl --fail --silent --show-error "http://127.0.0.1:${backend_port}/ready"
"${compose[@]}" --profile pgvector down --volumes --remove-orphans

export CACHE_BACKEND=memory
export MOCK_EMBEDDING_DIMENSIONS=0
unset DATABASE_URL

if "${compose[@]}" up --no-build --detach --wait --wait-timeout 45; then
  echo "Invalid backend configuration unexpectedly became healthy" >&2
  exit 1
fi
