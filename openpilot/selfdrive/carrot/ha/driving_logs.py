"""Upload finalized log segments directly to HA using existing discovery.

No extra Worker polling, no logger files modified, no writes in the Git tree.
Camera MP4 is a stream-copy derivative; the original TS is retained on HA too.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import quote

CHUNK = 256 * 1024
SEGMENT = re.compile(r'^[A-Za-z0-9_|.-]{1,96}--[0-9]{1,6}$')


def credential(token):
  return hmac.new(token.encode(), b'carrot-driving-logs-v1', hashlib.sha256).hexdigest()


def completed(root):
  candidates = []
  for directory in root.iterdir() if root.exists() else []:
    if directory.is_symlink() or not directory.is_dir() or not SEGMENT.fullmatch(directory.name):
      continue
    entries = list(directory.iterdir())
    if any(p.name.endswith('.lock') for p in entries):
      continue
    rlog = next((directory / f for f in ('rlog.zst', 'rlog.bz2', 'rlog')
                 if (directory / f).is_file() and not (directory / f).is_symlink()), None)
    video = next((directory / f for f in ('qcamera.ts', 'qcamera.mp4')
                  if (directory / f).is_file() and not (directory / f).is_symlink()), None)
    if not rlog or not video or not rlog.stat().st_size or not video.stat().st_size:
      continue
    recorded = video.stat().st_mtime
    if time.time() - max(p.stat().st_mtime for p in (rlog, video)) < 10:
      continue
    candidates.append((directory, recorded, rlog, video))
  return sorted(candidates, key=lambda item: (item[1], item[0].name), reverse=True)


async def prepare_video(video, working):
  if video.suffix == '.mp4':
    return video
  binary = shutil.which('ffmpeg')
  if not binary:
    raise OSError('ffmpeg is required to remux finalized qcamera for HA')
  output = working / 'qcamera.mp4'
  output.unlink(missing_ok=True)
  process = await asyncio.create_subprocess_exec(
    'nice', '-n', '19', binary, '-nostdin', '-hide_banner', '-loglevel', 'error',
    '-i', str(video), '-c', 'copy', '-movflags', '+faststart', '-y', str(output),
    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
  try:
    await asyncio.wait_for(process.wait(), 90)
    if process.returncode or not output.is_file() or not output.stat().st_size:
      raise OSError('Camera remux failed')
  finally:
    if process.returncode is None:
      process.kill()
      await process.wait()
  return output


async def transfer(client, base, directory, recorded, rlog, video, working):
  mp4 = await prepare_video(video, working)
  duration = None
  if probe := shutil.which('ffprobe'):
    process = await asyncio.create_subprocess_exec(probe, '-v', 'error', '-show_entries', 'format=duration',
                                                  '-of', 'json', str(mp4), stdout=asyncio.subprocess.PIPE,
                                                  stderr=asyncio.subprocess.DEVNULL)
    try:
      output, _ = await asyncio.wait_for(process.communicate(), 15)
      if process.returncode == 0:
        value = float(json.loads(output)['format']['duration'])
        if 0 < value <= 1800:
          duration = value
    except (ValueError, KeyError):
      pass
    finally:
      if process.returncode is None:
        process.kill()
        await process.wait()
  sources = {p.name: p for p in (rlog, video, mp4)}
  signatures = {f: (p.stat().st_size, p.stat().st_mtime_ns) for f, p in sources.items()}
  files = {f: value[0] for f, value in signatures.items()}
  async with client.post(base + '/begin', json={'segment': directory.name, 'recorded': recorded, 'duration': duration, 'files': files}, allow_redirects=False) as response:
    response.raise_for_status()
    status = await response.json()
  if not status.get('accepted') or status.get('complete'):
    return
  hashes = {}
  for filename, source in sources.items():
    offset = status['offsets'][filename]
    if type(offset) is not int or not 0 <= offset <= files[filename]:
      raise ValueError('Invalid HA upload offset')
    digest = hashlib.sha256()
    with source.open('rb') as stream:
      position = 0
      while data := await asyncio.to_thread(stream.read, CHUNK):
        digest.update(data)
        end = position + len(data)
        if end > offset:
          chunk = data[max(0, offset - position):]
          async with client.put(base + '/chunk/' + quote(directory.name, safe='') + '/' + quote(filename, safe=''),
                                data=chunk, headers={'X-Upload-Offset': str(max(position, offset))}, allow_redirects=False) as response:
            response.raise_for_status()
            ack = await response.json()
            if ack.get('offset') != end:
              raise ValueError('HA upload acknowledgement mismatch')
          # Keep disk and network work below the real-time driving processes.
          await asyncio.sleep(.05)
        position = end
    if (source.stat().st_size, source.stat().st_mtime_ns) != signatures[filename]:
      raise OSError('Finalized source changed during transfer')
    hashes[filename] = digest.hexdigest()
  async with client.post(base + '/commit', json={'segment': directory.name, 'hashes': hashes}, allow_redirects=False) as response:
    response.raise_for_status()
    result = await response.json()
    if result.get('complete') is not True:
      raise ValueError('HA did not commit the segment')


async def run(resolved, root=Path('/data/media/0/realdata'), state_root=Path('/data/carrot_ha/driving_logs')):
  import aiohttp
  state_root.mkdir(parents=True, exist_ok=True)
  working = state_root / 'transfer'
  working.mkdir(exist_ok=True)
  identity = hashlib.sha256((resolved['ha_url'] + resolved['device']).encode()).hexdigest()[:16]
  receipt = state_root / (identity + '.json')
  try:
    done = json.loads(receipt.read_text()) if receipt.exists() else {}
  except (ValueError, OSError):
    done = {}
  base = resolved['ha_url'].rstrip('/') + '/api/carrot_ha/v1/driving_logs_upload/' + quote(resolved['device'], safe='')
  timeout = aiohttp.ClientTimeout(total=60)
  delay = 15
  last_check = 0
  floor = 0
  async with aiohttp.ClientSession(timeout=timeout, headers={'Authorization': 'Bearer ' + credential(resolved['terminal_token'])}) as client:
    while True:
      try:
        if time.monotonic() - last_check >= 15:
          async with client.get(base + '/state', allow_redirects=False) as response:
            response.raise_for_status()
            inventory = await response.json()
          floor = inventory.get('floor', 0)
          if not isinstance(floor, (int, float)) or not isinstance(inventory.get('complete'), dict):
            raise ValueError('Invalid HA log inventory')
          done = inventory['complete']
          last_check = time.monotonic()
        items = await asyncio.to_thread(completed, root)
        names = {item[0].name for item in items}
        done = {key: value for key, value in done.items() if key in names}
        # Re-evaluate newest first each pass; never bury new logs behind backlog.
        item = next((item for item in items if item[1] > floor and done.get(item[0].name) != item[1]), None)
        if item:
          await transfer(client, base, *item, working)
          done[item[0].name] = item[1]
          temporary = receipt.with_suffix('.tmp')
          temporary.write_text(json.dumps(done))
          temporary.replace(receipt)
          (working / 'qcamera.mp4').unlink(missing_ok=True)
          delay = 1
        else:
          delay = 15
      except (aiohttp.ClientError, OSError, ValueError, KeyError, TimeoutError) as error:
        print('[Carrot HA logs] transfer deferred: ' + type(error).__name__, flush=True)
        delay = min(max(15, delay * 2), 120)
      await asyncio.sleep(delay)
