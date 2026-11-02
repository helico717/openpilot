"""Stream-copy a finalized video with IQpilot's existing PyAV dependency."""
import argparse
from pathlib import Path


def remux(source, destination):
    import av
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve() or source.is_symlink() or not source.is_file():
        raise ValueError('Invalid source video')
    if destination.exists() or destination.is_symlink():
        raise ValueError('Output must not already exist')
    complete = False
    try:
        packets = 0
        with av.open(str(source)) as reader:
            video = reader.streams.video[0]
            with av.open(str(destination), 'w', options={'movflags': '+faststart', 'avoid_negative_ts': 'make_zero'}) as writer:
                if hasattr(writer, 'add_stream_from_template'):
                    target = writer.add_stream_from_template(video)
                else:
                    target = writer.add_stream(template=video)
                for packet in reader.demux(video):
                    if packet.dts is None:
                        continue
                    packet.stream = target
                    writer.mux(packet)
                    packets += 1
        if not packets or not destination.stat().st_size:
            raise ValueError('No finalized video packets')
        complete = True
    finally:
        if not complete:
            destination.unlink(missing_ok=True)


async def prepare_video(video, working):
    import asyncio
    import sys
    if video.suffix == '.mp4':
        return video
    output = working / 'qcamera.mp4'
    output.unlink(missing_ok=True)
    process = await asyncio.create_subprocess_exec(
        'nice', '-n', '19', sys.executable, '-m', __name__, str(video), str(output),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(process.wait(), 90)
        if process.returncode or not output.is_file() or not output.stat().st_size:
            raise OSError('PyAV remux failed')
        return output
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    remux(args.source, args.destination)
