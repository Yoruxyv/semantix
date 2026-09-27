#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose -f docker-compose.prod.yml)
python_command="${PYTHON_COMMAND:-python3}"
upstream_file="$(mktemp)"

cleanup() {
  "${compose[@]}" down --volumes --remove-orphans
  rm -f "$upstream_file"
}
trap cleanup EXIT

cp frontend/upstream.prod.conf "$upstream_file"
export SEMANTIX_UPSTREAM_FILE="$upstream_file"

generate_secret() {
  "$python_command" -c 'import secrets; print(secrets.token_urlsafe(32))'
}

export POSTGRES_DB="${POSTGRES_DB:-semantix}"
export POSTGRES_MIGRATION_USER="${POSTGRES_MIGRATION_USER:-semantix_migrator}"
export POSTGRES_MIGRATION_PASSWORD="${POSTGRES_MIGRATION_PASSWORD:-$(generate_secret)}"
export POSTGRES_RUNTIME_USER="${POSTGRES_RUNTIME_USER:-semantix_runtime}"
export POSTGRES_RUNTIME_PASSWORD="${POSTGRES_RUNTIME_PASSWORD:-$(generate_secret)}"

smoke_token="${SMOKE_AUTH_TOKEN:-$(generate_secret)}"
viewer_token="$(generate_secret)"
operator_token="$(generate_secret)"
scoped_admin_token="$(generate_secret)"
export SEMANTIX_E2E_TOKEN="$smoke_token"
export SEMANTIX_E2E_VIEWER_TOKEN="$viewer_token"
export SEMANTIX_E2E_OPERATOR_TOKEN="$operator_token"
export SEMANTIX_E2E_SCOPED_ADMIN_TOKEN="$scoped_admin_token"
export AUTH_PRINCIPALS="$(
  "$python_command" -c \
    'import hashlib, json, sys; print(json.dumps([{"name": name, "token_sha256": hashlib.sha256(token.encode()).hexdigest(), "role": role, "namespaces": namespaces} for name, token, role, namespaces in zip(("global-admin", "viewer", "operator", "scoped-admin"), sys.argv[1:], ("admin", "viewer", "operator", "admin"), (("*",), ("alpha",), ("alpha",), ("alpha",)))]))' \
    "$smoke_token" "$viewer_token" "$operator_token" "$scoped_admin_token"
)"

"${compose[@]}" up --build --detach --wait --wait-timeout 180

curl --fail --silent --show-error http://127.0.0.1:18080/health
curl --fail --silent --show-error http://127.0.0.1:18080/ready

first="$(
  curl --fail --silent --show-error \
    --header "Authorization: Bearer ${smoke_token}" \
    --header "Content-Type: application/json" \
    --data '{"prompt":"Hardened smoke cache verification"}' \
    http://127.0.0.1:18080/api/v1/query
)"
second="$(
  curl --fail --silent --show-error \
    --header "Authorization: Bearer ${smoke_token}" \
    --header "Content-Type: application/json" \
    --data '{"prompt":"Hardened smoke cache verification"}' \
    http://127.0.0.1:18080/api/v1/query
)"

"$python_command" -c \
  'import json, sys; payload = json.loads(sys.argv[1]); assert payload["cache_hit"] is False; assert payload["provider_called"] is True' \
  "$first"
"$python_command" -c \
  'import json, sys; payload = json.loads(sys.argv[1]); assert payload["cache_hit"] is True; assert payload["provider_called"] is False' \
  "$second"

if (( $# > 0 )); then
  "$@"
fi
