#!/usr/bin/env bash
# Run from packages/cache; infrastructure smoke owns container checks and cleanup.
set -euo pipefail

: "${RUNNER_TEMP:?Missing RUNNER_TEMP}"
: "${REDIS_TEST_URL:?Missing REDIS_TEST_URL}"
: "${REDIS_TEST_VERSION:?Missing REDIS_TEST_VERSION}"
: "${REDIS_TEST_CONTAINER:?Missing REDIS_TEST_CONTAINER}"
for required in .venv/bin/python pyproject.toml dist/semantix_cache-0.1.0-py3-none-any.whl \
  tests/redis_infrastructure_smoke.py tests/redis_wheel_smoke.py ../../ops/ci/required_tests.py; do
  if [[ ! -f "$required" ]]; then
    printf 'Missing input %s; run from packages/cache after building artifacts\n' "$required" >&2
    exit 1
  fi
done

for driver in 7.4.1 8.0.1; do
  target="$RUNNER_TEMP/redis-driver-$driver"
  # Never overwrite another invocation's environments or failed evidence.
  mkdir "$target"
  uv venv --python .venv/bin/python "$target/tests"
  driver_python="$target/tests/bin/python"
  # Replace only the expected locked baseline; reject missing/duplicate/drifted pins.
  uv export --locked --extra dev --no-emit-project --no-hashes --no-annotate |
    awk -v driver="$driver" '
      $0 == "redis==8.1.0" { count++; $0 = "redis==" driver }
      { print }
      END {
        if (count != 1) {
          print "Expected exactly one locked redis==8.1.0 pin" > "/dev/stderr"
          exit 1
        }
      }
    ' > "$target/requirements.txt"
  uv pip install --python "$driver_python" -r "$target/requirements.txt" --editable '.[redis]'
  "$driver_python" -c "from importlib.metadata import version; import sys; assert version('redis') == sys.argv[1]; print('Verified redis-py', version('redis'))" "$driver"
  "$driver_python" tests/redis_infrastructure_smoke.py --verify-version
  "$driver_python" -m mypy src examples
  "$driver_python" ../../ops/ci/required_tests.py redis "$target/tests.xml" -- tests/test_redis*.py tests/test_inspection.py -k redis
  "$driver_python" tests/redis_infrastructure_smoke.py
  uv venv --python .venv/bin/python "$target/wheel"
  wheel_python="$target/wheel/bin/python"
  uv pip install --python "$wheel_python" "dist/semantix_cache-0.1.0-py3-none-any.whl[redis]" "redis==$driver"
  "$wheel_python" -c "from importlib.metadata import version; import sys; assert version('redis') == sys.argv[1]; print('Verified wheel redis-py', version('redis'))" "$driver"
  "$wheel_python" -I tests/redis_wheel_smoke.py
done
