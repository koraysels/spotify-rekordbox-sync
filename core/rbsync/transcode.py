"""Re-encode downloaded audio to an mp3 whose bitrate is matched to its source.

Only ffmpeg is assumed: spotDL's ``--download-ffmpeg`` ships no ffprobe, so the
source bitrate is measured with ffmpeg itself.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from pathlib import Path

MP3_STEPS: tuple[int, ...] = (128, 160, 192, 224, 256)
LOWQ_COMMENT = "lowq"

_HEADROOM = 1.25
_SIZE_RE = re.compile(r"audio:\s*(\d+(?:\.\d+)?)\s*(KiB|kB)")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


class TranscodeError(RuntimeError):
    pass


def mp3_bitrate_for(source_kbps: float) -> int:
    """The smallest mp3 step with 25% headroom over the source, capped at 256."""
    if source_kbps <= 0:
        raise ValueError("source bitrate must be positive")
    target = _HEADROOM * source_kbps
    return next((s for s in MP3_STEPS if s >= target), MP3_STEPS[-1])


def _popen_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def measure_audio_kbps(ffmpeg: str, path: Path) -> float:
    """Average audio bitrate (cover art excluded), measured by a stream-copy pass."""
    res = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path), "-map", "0:a:0", "-c", "copy", "-f", "null", "-"],
        capture_output=True, text=True, errors="replace", **_popen_kwargs(),
    )
    err = res.stderr
    sizes = _SIZE_RE.findall(err)
    dur = _DURATION_RE.search(err)
    if not sizes or not dur:
        raise TranscodeError(f"could not measure bitrate of {path.name}")
    amount, unit = sizes[-1]
    seconds = int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3])
    if seconds <= 0:
        raise TranscodeError(f"could not measure bitrate of {path.name}")
    size_bytes = float(amount) * (1024 if unit == "KiB" else 1000)
    return size_bytes * 8 / 1000 / seconds


def encode_mp3_lowq(
    ffmpeg: str,
    source: Path,
    target: Path,
    kbps: int,
    cancel: threading.Event | None = None,
) -> None:
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-i", str(source),
        "-map", "0:a:0", "-map", "0:v?", "-map_metadata", "0",
        # Opus/Ogg keep their tags on the stream, not the file; merge those in too.
        "-map_metadata", "0:s:a:0",
        "-c:a", "libmp3lame", "-b:a", f"{kbps}k",
        "-c:v", "copy", "-disposition:v", "attached_pic",
        "-id3v2_version", "3", "-metadata", f"comment={LOWQ_COMMENT}",
        str(target),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True, errors="replace", **_popen_kwargs(),
    )
    err_chunks: list[str] = []
    reader = threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True)
    reader.start()
    try:
        _wait(proc, cancel, target, reader)
    finally:
        proc.stderr.close()
    if proc.returncode != 0:
        target.unlink(missing_ok=True)
        lines = [ln for ln in "".join(err_chunks).splitlines() if ln.strip()]
        raise TranscodeError(lines[-1] if lines else f"ffmpeg exited {proc.returncode}")


def _wait(proc, cancel, target, reader) -> None:
    while True:
        if cancel is not None and cancel.is_set() and proc.poll() is None:
            proc.kill()
            proc.wait()
            reader.join()
            target.unlink(missing_ok=True)
            raise TranscodeError("cancelled")
        try:
            proc.wait(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            continue
    reader.join()
