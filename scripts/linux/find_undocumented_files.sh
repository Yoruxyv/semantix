#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"

is_documentation_candidate() {
  local path="$1"
  local name="${path##*/}"
  local extension=""

  [[ "$name" == *.* ]] && extension=".${name##*.}"
  extension="$(printf '%s' "$extension" | tr '[:upper:]' '[:lower:]')"

  case "$extension" in
    .conf|.css|.example|.html|.js|.json|.mjs|.ps1|.py|.sh|.sql|.toml|.ts|.tsx|.yaml|.yml)
      ;;
    *)
      return 1
      ;;
  esac

  case "$path" in
    docs/*|apps/server/tests/*|apps/web/tests/*|.github/ISSUE_TEMPLATE/*)
      return 1
      ;;
  esac

  case "$name" in
    __init__.py|package.json|package-lock.json|uv.lock)
      return 1
      ;;
  esac

  return 0
}

declare -a project_files=()
declare -a markdown_files=()
declare -a candidates=()
declare -a undocumented=()
declare -A ignored_tracked=()

while IFS= read -r -d '' ignored_path; do
  ignored_tracked["$ignored_path"]=1
done < <(
  git -C "$repo_root" ls-files \
    --cached \
    --ignored \
    --exclude-standard \
    -z
)

while IFS= read -r -d '' path; do
  [[ -z "${ignored_tracked[$path]+present}" ]] || continue
  project_files+=("$path")
  [[ "${path,,}" == *.md ]] && markdown_files+=("$path")
  is_documentation_candidate "$path" && candidates+=("$path")
done < <(
  git -C "$repo_root" ls-files \
    --cached \
    --others \
    --exclude-standard \
    -z
)

documentation_corpus=""
for markdown_file in "${markdown_files[@]}"; do
  documentation_corpus+="$(cat "$repo_root/$markdown_file")"$'\n'
done

for candidate in "${candidates[@]}"; do
  if ! grep -Fqi -- "$candidate" <<< "$documentation_corpus"; then
    undocumented+=("$candidate")
  fi
done

printf '%s\n' '========================================================================'
printf 'SEMANTIX DOCUMENTATION COVERAGE REPORT\n'
printf '%s\n' '========================================================================'
printf 'Definition: documented means the exact repository-relative path appears in Markdown.\n'
printf 'Excluded: tests, package markers, package manifests, lockfiles, ignored files,\n'
printf '          dependencies, and build output.\n'
printf 'Scanned files: %s\n' "${#candidates[@]}"
printf 'Undocumented files: %s\n' "${#undocumented[@]}"

if (( ${#undocumented[@]} == 0 )); then
  printf '\nEvery scanned project file is referenced in the documentation.\n'
  exit 0
fi

while IFS= read -r extension; do
  count=0
  for path in "${undocumented[@]}"; do
    name="${path##*/}"
    current_extension=".${name##*.}"
    current_extension="${current_extension,,}"
    [[ "$current_extension" == "$extension" ]] && count=$((count + 1))
  done

  upper_extension="$(printf '%s' "$extension" | tr '[:lower:]' '[:upper:]')"
  file_label="files"
  (( count == 1 )) && file_label="file"
  printf '\n[%s] %s undocumented %s\n' \
    "$upper_extension" "$count" "$file_label"
  printf '%s\n' '------------------------------------------------------------------------'
  printf '%s\n' "${undocumented[@]}" |
    while IFS= read -r path; do
      name="${path##*/}"
      current_extension=".${name##*.}"
      current_extension="${current_extension,,}"
      [[ "$current_extension" == "$extension" ]] && printf '  %s\n' "$path"
    done
done < <(
  for path in "${undocumented[@]}"; do
    name="${path##*/}"
    extension=".${name##*.}"
    printf '%s\n' "${extension,,}"
  done | sort -u
)
