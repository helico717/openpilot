#!/usr/bin/env bash
set -euo pipefail
upstream_ref="${UPSTREAM_REF:-upstream/happymaj11r/carrot-wip-model_selector}"
target_branch="${TARGET_BRANCH:-carrot-wip-model_selector-ha}"
base_commit=$(git rev-parse HEAD)
if git merge-base --is-ancestor "$upstream_ref" HEAD; then
  echo "Already up-to-date with $upstream_ref."
  exit 0
fi
# Defer the merge commit so workflow modify/delete conflicts can be resolved
# before Git's nonzero merge result terminates this step.
merge_status=0
git merge --no-commit --no-ff "$upstream_ref" || merge_status=$?
if [ "${SYNC_WORKFLOWS:-false}" != "true" ]; then
  # Clear unmerged index stages, including upstream-only files deleted locally.
  git rm -r -f --ignore-unmatch -- .github/workflows/
  git restore --source="$base_commit" --staged --worktree --no-overlay -- .github/workflows/
fi
if [ -n "$(git ls-files --unmerged)" ]; then
  echo "Unresolved source conflicts; refusing to discard fork or upstream code."
  git diff --name-only --diff-filter=U
  git merge --abort
  exit 1
fi
if ! git rev-parse -q --verify MERGE_HEAD >/dev/null; then
  echo "Merge did not start (status $merge_status)."
  exit 1
fi
git commit -m "chore: auto-sync upstream happymaj11r/carrot-wip-model_selector"
if [ "${SYNC_WORKFLOWS:-false}" != "true" ]; then
  git diff --exit-code "$base_commit" HEAD -- .github/workflows/
fi
if [ "${SYNC_PUSH:-true}" = "true" ]; then
  git push origin "$target_branch"
fi
