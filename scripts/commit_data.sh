#!/usr/bin/env bash
# Commit evidence/results produced by a job and push with rebase retries.
# Conflicts: append-only logs merge by union (.gitattributes); for anything else (derived
# parquet tables, the Wayback digest cache) this job's version wins (-X theirs during rebase).
# Derived tables are regenerated from raw evidence on every parse, so nothing is lost.
set -uo pipefail
msg="$1"; shift
for p in data reports site docs/methodology.md; do [ -e "$p" ] && git add -A "$p"; done
if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
git commit -q -m "$msg"
for i in 1 2 3 4 5 6; do
  git fetch -q origin "${GITHUB_REF_NAME}"
  if git rebase -q -X theirs "origin/${GITHUB_REF_NAME}"; then
    if git push -q origin "HEAD:${GITHUB_REF_NAME}"; then echo "pushed"; exit 0; fi
  else
    # Unresolvable (e.g. modify/delete) conflict: take our side for every conflicted path.
    git diff --name-only --diff-filter=U | while read -r f; do
      git checkout --theirs -- "$f" 2>/dev/null || git rm -q --cached "$f"; git add "$f" 2>/dev/null
    done
    if GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 && git push -q origin "HEAD:${GITHUB_REF_NAME}"; then
      echo "pushed after resolving conflicts"; exit 0
    fi
    git rebase --abort 2>/dev/null || true
  fi
  sleep $((i * 7))
done
echo "push failed" >&2; exit 1
