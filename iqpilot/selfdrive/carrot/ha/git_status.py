"""Read-only checkout identity; called on the existing sample thread."""
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import time

_cached = {}
_next_read = 0

def checkout_status():
    global _cached, _next_read
    now = time.monotonic()
    if now < _next_read:
        return dict(_cached)
    _next_read = now + 60
    try:
        def git(*args):
            return subprocess.run(['git', '-C', str(Path(__file__).resolve().parents[3]), *args],
                                  capture_output=True, text=True, timeout=2, check=True).stdout.strip()
        sha = git('rev-parse', 'HEAD')
        branch = git('rev-parse', '--abbrev-ref', 'HEAD')
        remote = git('remote', 'get-url', 'origin')
        match = re.fullmatch(r'(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?/?', remote)
        if not re.fullmatch(r'[0-9a-f]{40}', sha) or not match:
            return {}
        _cached = {'comma_git_commit': sha, 'comma_git_branch': branch if branch != 'HEAD' else None,
                   'comma_git_repository': match.group(1),
                   'comma_git_measured_at': datetime.now(timezone.utc).isoformat()}
        return dict(_cached)
    except (OSError, subprocess.SubprocessError):
        # Keep the old observation time on a failed read.
        return dict(_cached)
