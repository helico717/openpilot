#!/usr/bin/env python3
"""Update the HA branch using IQ.OS's supported Git interface; no reboot/OS write."""
from pathlib import Path
import subprocess


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def update(repo=Path('/data/openpilot'), params=Path('/data/params/d'), restricted=None):
    repo = Path(repo).resolve()
    if ((params/'IsOffroad').read_text().strip(), (params/'IsOnroad').read_text().strip()) != ('1','0'):
        raise ValueError('Explicit offroad state required')
    if git(repo,'branch','--show-current') != 'iq-ha':
        raise ValueError('Use the iq-ha branch')
    if git(repo,'remote','get-url','origin') not in (
        'https://github.com/helico717/openpilot.git','git@github.com:helico717/openpilot.git'):
        raise ValueError('Unexpected source repository')
    vendor = repo/'vendor/iqpilot'
    for path in (repo,vendor):
        if git(path,'diff','--name-only') or git(path,'diff','--cached','--name-only'):
            raise ValueError('Tracked changes; refusing update')
    git(repo,'fetch','origin')
    # Check before pull: root helper accepts only its normal origin operation.
    git(repo,'merge-base','--is-ancestor','HEAD','refs/remotes/origin/iq-ha')
    target = git(repo,'rev-parse','refs/remotes/origin/iq-ha')
    pin = git(repo,'ls-tree',target,'vendor/iqpilot').split()[2]
    if git(vendor,'rev-parse','HEAD') != pin:
        # Download first; the running source and vendor working tree stay intact
        # if the network fails. This is normal Git in the vendor submodule.
        git(vendor,'fetch','--depth','1','origin',pin)
    git(repo,'config','pull.ff','only')
    if restricted is None:
        restricted=Path('/usr/libexec/iqos/iq-git-update').is_file()
    if restricted:
        git(repo,'pull','origin')
    else:
        git(repo,'pull','--ff-only')
    git(repo,'submodule','sync','--recursive')
    git(repo,'submodule','update','--init','--no-fetch','--','vendor/iqpilot')
    if git(repo,'rev-parse','HEAD') != target or git(vendor,'rev-parse','HEAD') != pin:
        raise ValueError('Source/vendor did not reach the expected pins; do not reboot')
    print('IQ_HA_UPDATE_READY',target,'IQ',pin)
    print('Owner: reboot using the device menu. The original IQ launcher handles any required OS update.')


if __name__=='__main__':
    try:update()
    except Exception:
        raise SystemExit('IQ_HA_UPDATE_FAILED: do not reboot; report the failed step. No reset/clean performed.')
