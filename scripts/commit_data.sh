#!/usr/bin/env bash
# Commit evidence/results produced by a job and push with rebase retries.
set -euo pipefail
msg="$1"; shift
git add -A data reports site docs/methodology.md 2>/dev/null || true
if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
git commit -q -m "$msg"
for i in 1 2 3 4 5; do
  if git pull -q --rebase origin "${GITHUB_REF_NAME}" && git push -q origin "HEAD:${GITHUB_REF_NAME}"; then
    echo "pushed"; exit 0
  fi
  sleep $((i * 7))
done
echo "push failed" >&2; exit 1
