#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
expected=5c9291b9df6d90007d73ecd749b135bd5008e80d
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
