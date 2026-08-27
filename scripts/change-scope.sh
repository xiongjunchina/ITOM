#!/usr/bin/env bash
# Classify repository changes for fast checks and component-scoped releases.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
BASE_REF="${1:-${BASE_REF:-HEAD}}"
HEAD_REF="${2:-${HEAD_REF:-WORKTREE}}"

git -C "$REPO_ROOT" rev-parse --verify "$BASE_REF^{commit}" >/dev/null 2>&1 || {
  echo "!! Unknown BASE_REF: $BASE_REF" >&2
  exit 2
}
if [ "$HEAD_REF" != WORKTREE ]; then
  git -C "$REPO_ROOT" rev-parse --verify "$HEAD_REF^{commit}" >/dev/null 2>&1 || {
    echo "!! Unknown HEAD_REF: $HEAD_REF" >&2
    exit 2
  }
fi

backend=0
frontend=0
shared=0
changed=0

classify_paths() {
  if [ "$HEAD_REF" = WORKTREE ]; then
    git -C "$REPO_ROOT" diff --name-only "$BASE_REF"
    git -C "$REPO_ROOT" ls-files --others --exclude-standard
  else
    git -C "$REPO_ROOT" diff --name-only "$BASE_REF" "$HEAD_REF"
  fi
}

while IFS= read -r path; do
  [ -n "$path" ] || continue
  changed=1
  case "$path" in
    backend/*) backend=1 ;;
    frontend/*) frontend=1 ;;
    README.md|docs/*) ;;
    .github/*|deploy/*|scripts/*|AGENTS.md|.gitignore) shared=1 ;;
    *) shared=1 ;;
  esac
done < <(classify_paths | sort -u)

if [ "$changed" = 0 ]; then
  scope=none
elif [ "$shared" = 1 ] || { [ "$backend" = 1 ] && [ "$frontend" = 1 ]; }; then
  scope=all
elif [ "$backend" = 1 ]; then
  scope=backend
elif [ "$frontend" = 1 ]; then
  scope=frontend
else
  scope=docs
fi

printf '%s\n' "$scope"
