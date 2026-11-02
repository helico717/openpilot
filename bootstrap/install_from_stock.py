#!/usr/bin/env python3
"""Activate a fully downloaded, Git-managed HA candidate from matching stock IQ.

Run from a separate iq-ha Git clone with its vendor initialized. No source copying,
reset/clean, automatic reboot, OS write or credential restore. Runtime cache alone
is moved out of the Git tree; Git performs every program-file change.
"""
import json
import os
from pathlib import Path
import subprocess

ORIGIN = 'https://github.com/helico717/openpilot.git'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def parked(params):
    if ((params / 'IsOffroad').read_text().strip(), (params / 'IsOnroad').read_text().strip()) != ('1', '0'):
        raise ValueError('Explicit offroad state required')


def validate(stage, repo, params, version):
    manifest = json.loads((stage / 'HA_CANDIDATE.json').read_text())
    parked(params)
    if (params / 'UpdaterState').read_text().strip() != 'idle':
        raise ValueError('Stock updater is not idle; wait for completion')
    if version.read_text().strip().removeprefix('IQ.OS ') != manifest['required_os']:
        raise ValueError('Installed OS differs from candidate; do not downgrade')
    if git(repo, 'rev-parse', 'HEAD') != manifest['iqpilot_sha']:
        raise ValueError('Stock IQ version differs from candidate')
    for path in (stage, repo, stage / 'vendor/iqpilot'):
        if git(path, 'diff', '--name-only') or git(path, 'diff', '--cached', '--name-only'):
            raise ValueError('Tracked changes found; refusing')
    if git(stage / 'vendor/iqpilot', 'rev-parse', 'HEAD') != manifest['iqpilot_sha']:
        raise ValueError('Vendor checkout differs from candidate')
    if subprocess.run(['git', '-C', str(repo), 'show-ref', '--verify', '--quiet', 'refs/heads/iq-ha']).returncode == 0:
        raise ValueError('Local iq-ha already exists; use its normal update path')
    for relative in ('iqpilot/system/camerad/camerad', 'iqpilot/system/loggerd/encoderd'):
        target = stage / relative
        if not target.is_file() or not os.access(target, os.X_OK):
            raise ValueError('Vendor runtime download incomplete')
    return manifest


def activate(stage, repo=Path('/data/openpilot'), params=Path('/data/params/d'),
             version=Path('/VERSION'), runtime=Path('/data/iqpilot-ha-runtime')):
    stage, repo = Path(stage).resolve(), Path(repo).resolve()
    if stage == repo:
        raise ValueError('Run from a separate fully initialized candidate clone')
    validate(stage, repo, params, version)
    candidate_sha = git(stage, 'rev-parse', 'HEAD')
    git(repo, 'fetch', '--no-tags', str(stage), candidate_sha)
    parked(params)
    cache = repo / '.iqpilot'
    migrated = False
    if cache.is_dir() and not cache.is_symlink():
        if runtime.exists() or runtime.is_symlink():
            raise ValueError('Separate runtime directory already exists; review before switching')
        # This is cached runtime state, not a manual source deployment.
        cache.rename(runtime)
        migrated = True
    try:
        git(repo, 'checkout', '--no-overwrite-ignore', '--no-recurse-submodules', '-b', 'iq-ha', candidate_sha)
    except subprocess.CalledProcessError:
        if migrated and not cache.exists() and not cache.is_symlink():
            runtime.rename(cache)
        raise
    git(repo, 'submodule', 'sync', '--recursive')
    # Dissociate keeps the installed checkout independent of the staging folder.
    git(repo, 'submodule', 'update', '--init', '--reference', str(stage / 'vendor/iqpilot'),
        '--dissociate', '--', 'vendor/iqpilot')
    git(repo, 'remote', 'set-url', 'origin', ORIGIN)
    git(repo, 'fetch', '--no-tags', 'origin', 'refs/heads/iq-ha:refs/remotes/origin/iq-ha')
    git(repo, 'branch', '--set-upstream-to=origin/iq-ha', 'iq-ha')
    if git(repo, 'rev-parse', 'HEAD') != candidate_sha or git(repo, 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Installed checkout is not the exact clean candidate')
    print('IQ_HA_INSTALLED', candidate_sha)
    print('Owner: restore HA settings, inspect diagnostics, then reboot using the device menu.')


if __name__ == '__main__':
    try:
        activate(Path(__file__).resolve().parents[1])
    except Exception as error:
        print('IQ_HA_NOT_READY: do not reboot; report the failed step before continuing.')
        raise SystemExit(str(error) if isinstance(error, ValueError) else type(error).__name__)
