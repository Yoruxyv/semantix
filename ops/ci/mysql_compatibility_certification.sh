#!/usr/bin/env bash
# Run from packages/cache after baseline certification; mysql_fixture.py owns all infrastructure.
set -euo pipefail

case "${1-}" in
  3.11) pairs=("8.4.12:1.2.1") ;;
  3.14) pairs=("8.4.11:1.2.3" "8.4.12:1.2.2") ;;
  *) printf 'Expected Python boundary 3.11 or 3.14\n' >&2; exit 1 ;;
esac
: "${RUNNER_TEMP:?Missing RUNNER_TEMP}"
: "${GITHUB_WORKSPACE:?Missing GITHUB_WORKSPACE}"
for required in .venv/bin/python pyproject.toml .cache/mysql-coverage/.coverage.mysql \
  dist/semantix_cache-0.1.0-py3-none-any.whl ../../ops/ci/mysql_fixture.py \
  "$GITHUB_WORKSPACE/packages/cache/tests/mysql_wheel_smoke.py"; do
  if [[ ! -f "$required" ]]; then
    printf 'Missing input %s; run from packages/cache after baseline certification\n' "$required" >&2
    exit 1
  fi
done

coverage="$PWD/.cache/mysql-coverage/.coverage.mysql"
if [[ -e "$RUNNER_TEMP/mysql-baseline.coverage" || -L "$RUNNER_TEMP/mysql-baseline.coverage" ]]; then
  printf 'Refusing to overwrite an existing baseline coverage snapshot\n' >&2
  exit 1
fi
cp "$coverage" "$RUNNER_TEMP/mysql-baseline.coverage"
for pair in "${pairs[@]}"; do
  server="${pair%:*}"
  driver="${pair#*:}"
  target="$RUNNER_TEMP/mysql-$server-$driver"
  # Retain failed evidence and never reuse another invocation's environment.
  mkdir "$target"
  compat_python="$PWD/.venv/bin/python"
  if [[ "$driver" != "1.2.3" ]]; then
    uv venv --python .venv/bin/python "$target/tests"
    compat_python="$target/tests/bin/python"
    # Preserve locked test tools; replace only the driver in this disposable environment.
    uv export --locked --extra dev --no-emit-project --no-hashes --no-annotate |
      awk -v driver="$driver" '
        $0 == "pymysql==1.2.3" { count++; $0 = "pymysql==" driver }
        { print }
        END {
          if (count != 1) {
            print "Expected exactly one locked pymysql==1.2.3 pin" > "/dev/stderr"
            exit 1
          }
        }
      ' > "$target/requirements.txt"
    uv pip install --python "$compat_python" -r "$target/requirements.txt" --editable '.[mysql]'
  fi
  uv venv --python .venv/bin/python "$target/wheel"
  wheel_python="$target/wheel/bin/python"
  uv pip install --python "$wheel_python" "dist/semantix_cache-0.1.0-py3-none-any.whl[mysql]" "PyMySQL==$driver"
  uv run --no-sync python ../../ops/ci/mysql_fixture.py --server-version "$server" --pull-image
  uv run --no-sync python ../../ops/ci/mysql_fixture.py --server-version "$server" -- bash -euc '
    "$1" -c "from importlib.metadata import version; import sys; assert version(\"PyMySQL\") == sys.argv[1]; print(\"Verified PyMySQL\", version(\"PyMySQL\"))" "$2"
    "$1" -m pytest tests/test_mysql*.py --no-cov --junitxml="$4"
    "$1" -c "from xml.etree.ElementTree import parse; import sys; cases=parse(sys.argv[1]).findall(\".//testcase\"); assert len(cases) >= 213 and all(all(c.find(tag) is None for tag in (\"skipped\", \"failure\", \"error\")) for c in cases), \"Mandatory compatibility cases missing, skipped or failed\"" "$4"
    "$3" -c "from importlib.metadata import version; import sys; assert version(\"PyMySQL\") == sys.argv[1]" "$2"
    cd "$RUNNER_TEMP"
    "$3" -I "$GITHUB_WORKSPACE/packages/cache/tests/mysql_wheel_smoke.py"
  ' -- "$compat_python" "$driver" "$wheel_python" "$target/tests.xml"
done
# Extra certification runs must not overwrite the baseline coverage handoff.
cmp "$coverage" "$RUNNER_TEMP/mysql-baseline.coverage"
