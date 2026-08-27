#!/usr/bin/env bash
# Run the smallest safe local verification set without starting ITOM locally.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
BASE_REF="${BASE_REF:-HEAD}"
SCOPE="${SCOPE:-$($REPO_ROOT/scripts/change-scope.sh "$BASE_REF")}"

case "$SCOPE" in
  none|docs|backend|frontend|all) ;;
  *) echo "!! SCOPE must be none, docs, backend, frontend, or all"; exit 2 ;;
esac

echo "==> Change scope: $SCOPE (base: $BASE_REF)"
git -C "$REPO_ROOT" diff --check "$BASE_REF"

if [ "$SCOPE" = backend ] || [ "$SCOPE" = all ]; then
  PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/backend/.venv/bin/python}"
  [ -x "$PYTHON_BIN" ] || PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
  echo "==> Backend regression"
  (cd "$REPO_ROOT/backend" && "$PYTHON_BIN" -m pytest -q)
fi

if [ "$SCOPE" = frontend ] || [ "$SCOPE" = all ]; then
  echo "==> Frontend contract tests"
  (cd "$REPO_ROOT/frontend" && npm run test:contracts)
  echo "==> Frontend production build"
  (cd "$REPO_ROOT/frontend" && npm run build)
fi

echo "==> Fast check passed"
