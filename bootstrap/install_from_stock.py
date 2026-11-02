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
import tempfile

ORIGIN = 'https://github.com/helico717/openpilot.git'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def parked(params):
    if ((params / 'IsOffroad').read_text().strip(), (params / 'IsOnroad').read_text().strip()) != ('1', '0'):
        raise ValueError('Explicit offroad state required')


def preserve_python_caches(repo, paths, backup_parent):
    """Preserve only regenerable __pycache__/*.pyc collisions, never user data."""
    repo = Path(repo).resolve()
    for relative in paths:
        path = repo / relative
        if ('__pycache__' not in Path(relative).parts or path.suffix != '.pyc'
                or path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(repo)):
            raise ValueError('Non-cache untracked/ignored file collision; refusing without removing files')
    if not paths:
        return
    backup = Path(tempfile.mkdtemp(prefix='iq-ha-python-cache-', dir=backup_parent))
    for relative in paths:
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        (repo / relative).rename(target)
    print('PYTHON_CACHES_PRESERVED', len(paths), str(backup))


def prepare_vendor(stage, repo=Path('/data/openpilot')):
    """Copy through Git's local upload-pack protocol; shallow sources are valid.

    --reference rejects shallow stock installs. --no-local transfers independent
    objects without hardlinks/alternates, so later source changes cannot break it.
    """
    stage, repo = Path(stage).resolve(), Path(repo).resolve()
    manifest = json.loads((stage / 'HA_CANDIDATE.json').read_text())
    vendor = stage / 'vendor/iqpilot'
    if git(repo, 'rev-parse', 'HEAD') != manifest['iqpilot_sha']:
        raise ValueError('Stock IQ differs from staged candidate')
    if not (vendor / '.git').exists():
        git(stage, 'clone', '--no-local', '--depth', '1', str(repo), str(vendor))
        git(stage, 'submodule', 'absorbgitdirs', '--', 'vendor/iqpilot')
        git(stage, 'submodule', 'init', '--', 'vendor/iqpilot')
        url = git(stage, 'config', '-f', '.gitmodules', '--get', 'submodule.iqpilot-vendor.url')
        git(vendor, 'remote', 'set-url', 'origin', url)
    if git(vendor, 'rev-parse', 'HEAD') != manifest['iqpilot_sha']:
        raise ValueError('Prepared vendor does not match the pinned IQ source')
    print('IQ_VENDOR_READY', manifest['iqpilot_sha'])


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
             version=Path('/VERSION'), runtime=Path('/data/iqpilot-ha-runtime'), restricted=None):
    stage, repo = Path(stage).resolve(), Path(repo).resolve()
    if stage == repo:
        raise ValueError('Run from a separate fully initialized candidate clone')
    validate(stage, repo, params, version)
    candidate_sha = git(stage, 'rev-parse', 'HEAD')
    if restricted is None:
        restricted = Path('/usr/libexec/iqos/iq-git-update').is_file()
    if restricted:
        # The stock IQ.OS interface accepts only fetch/pull [origin] and
        # checkout <ref>. Use that interface; never bypass its wrapper.
        old_url = git(repo, 'remote', 'get-url', 'origin')
        old_fetch = git(repo, 'config', '--get-all', 'remote.origin.fetch').splitlines()
        try:
            git(repo, 'remote', 'set-url', 'origin', ORIGIN)
            git(repo, 'config', '--replace-all', 'remote.origin.fetch',
                '+refs/heads/iq-ha:refs/remotes/origin/iq-ha')
            git(repo, 'fetch', 'origin')
            if git(repo, 'rev-parse', 'refs/remotes/origin/iq-ha') != candidate_sha:
                raise ValueError('Published candidate changed; update and validate the staging clone first')
        except Exception:
            git(repo, 'remote', 'set-url', 'origin', old_url)
            for index, value in enumerate(old_fetch):
                git(repo, 'config', '--replace-all' if index == 0 else '--add', 'remote.origin.fetch', value)
            raise
        # The helper cannot accept --no-overwrite-ignore. Check ignored and
        # ordinary untracked collisions ourselves, before changing any files.
        tracked = set(git(stage, 'ls-tree', '-r', '--name-only', 'HEAD').splitlines())
        untracked = git(repo, 'ls-files', '--others', '--exclude-standard').splitlines()
        untracked += git(repo, 'ls-files', '--others', '--ignored', '--exclude-standard').splitlines()
        collisions = []
        for path in untracked:
            if path == '.iqpilot' or path.startswith('.iqpilot/'):
                continue  # Explicitly preserved below, never discarded.
            if any(path == target or path.startswith(target + '/') or target.startswith(path + '/') for target in tracked):
                collisions.append(path)
        preserve_python_caches(repo, sorted(set(collisions)), runtime.parent)
    else:
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
        if restricted:
            git(repo, 'branch', 'iq-ha', candidate_sha)
            git(repo, 'checkout', 'iq-ha')
        else:
            git(repo, 'checkout', '--no-overwrite-ignore', '--no-recurse-submodules', '-b', 'iq-ha', candidate_sha)
    except subprocess.CalledProcessError:
        if migrated and not cache.exists() and not cache.is_symlink():
            runtime.rename(cache)
        raise
    git(repo, 'clone', '--no-local', '--depth', '1', str(stage / 'vendor/iqpilot'), str(repo / 'vendor/iqpilot'))
    git(repo, 'submodule', 'absorbgitdirs', '--', 'vendor/iqpilot')
    git(repo, 'submodule', 'init', '--', 'vendor/iqpilot')
    git(repo, 'submodule', 'sync', '--recursive')
    url = git(stage, 'config', '-f', '.gitmodules', '--get', 'submodule.iqpilot-vendor.url')
    git(repo / 'vendor/iqpilot', 'remote', 'set-url', 'origin', url)
    git(repo, 'remote', 'set-url', 'origin', ORIGIN)
    if not restricted:
        git(repo, 'fetch', '--no-tags', 'origin', 'refs/heads/iq-ha:refs/remotes/origin/iq-ha')
    git(repo, 'branch', '--set-upstream-to=origin/iq-ha', 'iq-ha')
    if git(repo, 'rev-parse', 'HEAD') != candidate_sha or git(repo, 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Installed checkout is not the exact clean candidate')
    print('IQ_HA_INSTALLED', candidate_sha)
    print('Owner: restore HA settings, inspect diagnostics, then reboot using the device menu.')


if __name__ == '__main__':
    try:
        import sys
        stage = Path(__file__).resolve().parents[1]
        if sys.argv[1:] == ['--prepare-vendor']:
            prepare_vendor(stage)
        elif not sys.argv[1:]:
            activate(stage)
        else:
            raise ValueError('Use --prepare-vendor, or no arguments to activate')
    except Exception as error:
        print('IQ_HA_NOT_READY: do not reboot; report the failed step before continuing.')
        raise SystemExit(str(error) if isinstance(error, ValueError) else type(error).__name__)
