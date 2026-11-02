#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
expected=11fcd74243ede4f1f5df24db1ed2d44e2ac22664
cd "$root"
if [ -e vendor/iqpilot/.git ]; then
  git -C vendor/iqpilot diff --quiet
  git -C vendor/iqpilot diff --cached --quiet
fi
git submodule update --init --depth 1 -- vendor/iqpilot
actual=$(git -C vendor/iqpilot rev-parse HEAD)
if [ "$actual" != "$expected" ]; then
  echo 'IQpilot vendor version differs from the verified candidate; refusing launch.' >&2
  exit 1
fi
git -C vendor/iqpilot diff --quiet
git -C vendor/iqpilot diff --cached --quiet
# Runtime state remains outside both Git checkouts.
mkdir -p /data/iqpilot-ha-runtime
