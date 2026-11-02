#!/usr/bin/env python3
"""Export only public IQ CAN Python/DBC/schema files for isolated tests, no binaries."""
import argparse
from pathlib import Path
import subprocess

PREFIX = 'artifacts/package_runtime/'


def export(repo, output):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args])
    wanted = []
    for item in git('ls-tree', '-r', '-z', 'HEAD').split(b'\0'):
        if not item:
            continue
        metadata, raw = item.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        name = raw.decode()
        if mode != '120000' and kind == 'blob' and name.startswith(PREFIX + 'iqdbc/') and (
                name.endswith(('.py', '.capnp')) or name.endswith('/vw_meb.dbc')):
            wanted.append((name, oid))
    subprocess.run(['git', '-C', str(repo), '-c', 'fetch.negotiationAlgorithm=noop', 'fetch', '-q',
                    '--filter=blob:none', '--no-tags', '--no-write-fetch-head', '--stdin', 'origin'],
                   input='\n'.join(oid for _, oid in wanted).encode(), check=True)
    output.mkdir(parents=True, exist_ok=False)
    for name, oid in wanted:
        target = output / name[len(PREFIX):]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git('cat-file', 'blob', oid))
    print('CAN_RUNTIME_EXPORTED', len(wanted), 'public files; no binaries')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    export(args.repo, args.output)
