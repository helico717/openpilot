#!/usr/bin/env bash
# Git-only return from the IQ HA candidate to the pinned Carrot commit (ha-back).
# Never forces, resets, cleans or reboots; any conflict stops before the working tree changes.
# The owner reboots afterwards; Carrot's own launcher then reinstalls Carrot OS if needed.
set -euo pipefail

main() {
  local expected="${IQ_HA_CARROT_RETURN_SHA:-5ec4868a12a9038547b373eb95be3a5fa86d30aa}"  # override for tests only
  local params="${IQ_HA_PARAMS_DIR:-/data/params/d}"
  local root actual
  root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
  cd "$root"

  if [ "$(cat "$params/IsOnroad" 2>/dev/null)" = "1" ]; then
    echo 'Vehicle is onroad. Park and try again.' >&2
    return 1
  fi
  case "$(git remote get-url origin)" in
    *helico717/openpilot*) ;;
    *) echo 'origin is not helico717/openpilot; refusing.' >&2; return 1 ;;
  esac
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo 'Tracked files have local changes; refusing. Report this instead of resetting.' >&2
    return 1
  fi

  git fetch --no-tags origin +refs/heads/ha-back:refs/remotes/origin/ha-back
  actual=$(git rev-parse refs/remotes/origin/ha-back)
  if [ "$actual" != "$expected" ]; then
    echo "ha-back is $actual, expected $expected; refusing." >&2
    return 1
  fi

  # Without --force, Git refuses to overwrite untracked files and leaves HEAD unchanged.
  git checkout --no-recurse-submodules -B ha-back refs/remotes/origin/ha-back
  git submodule sync --recursive
  git submodule update --init --recursive
  test "$(git rev-parse HEAD)" = "$expected"
  echo "CARROT_CHECKED_OUT $expected"
  echo 'Reboot now. If Carrot OS must be reinstalled, keep the device powered until Carrot starts.'
}

# The checkout removes this file; running from a function keeps the parsed copy.
main "$@"
