#!/usr/bin/env bash
# Commit evidence/results produced by a job and push with rebase retries.
set -euo pipefail
msg="$1"; shift
for p in data reports site docs/methodology.md; do [ -e "$p" ] && git add -A "$p"; done
if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
git commit -q -m "$msg"
for i in 1 2 3 4 5; do
  # -X theirs: on a rebase conflict keep this job's version of the file. Append-only logs merge
  # by union (.gitattributes); the only other shared file is the Wayback digest cache, where
  # losing entries just means a capture is re-downloaded.
  if git pull -q --rebase -X theirs origin "${GITHUB_REF_NAME}" && git push -q origin "HEAD:${GITHUB_REF_NAME}"; then
    echo "pushed"; exit 0
  fi
  sleep $((i * 7))
done
echo "push failed" >&2; exit 1
