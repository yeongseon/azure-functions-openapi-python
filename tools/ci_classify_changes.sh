#!/usr/bin/env bash
set -euo pipefail

emit() {
  printf 'docs_only=%s\ndocs_changed=%s\nfull_required=%s\n' "$1" "$2" "$3"
}
trap 'echo "classifier error; running the full matrix" >&2; emit false true true' ERR

count=0
docs_only=true
docs_changed=false

while IFS= read -r f || [ -n "$f" ]; do
  [ -z "$f" ] && continue
  count=$((count + 1))
  case "$f" in
    mkdocs.yml | pyproject.toml | docs/*.py | docs/*.yml | docs/*.yaml | docs/*.json | \
    docs/*.toml | docs/*.js | docs/*.css | docs/*.html | docs/*.txt)
      docs_only=false
      docs_changed=true
      ;;
    src/* | tests/* | examples/* | scripts/* | tools/* | benchmarks/* | infra/* | \
    .github/* | Makefile | Dockerfile* | docker-compose* | requirements*.txt | *.lock | \
    hatch.toml | tox.ini | setup.cfg | setup.py | MANIFEST.in | .pre-commit-config.yaml | \
    host.json | local.settings*.json | *.py | *.sh)
      docs_only=false
      ;;
    *.md | docs/*.png | docs/*.jpg | docs/*.jpeg | docs/*.gif | docs/*.svg | \
    docs/*.webp | docs/*.ico)
      docs_changed=true
      ;;
    *)
      docs_only=false
      ;;
  esac
done

if [ "$count" -eq 0 ]; then
  echo "no changed files detected; running the full matrix" >&2
  emit false true true
  exit 0
fi

if [ "$docs_only" = true ]; then
  emit true true false
else
  emit false "$docs_changed" true
fi
