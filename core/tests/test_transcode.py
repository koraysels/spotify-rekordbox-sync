import json
import shutil
import subprocess
import threading

import pytest

from rbsync.transcode import (
    TranscodeError,
    encode_mp3_lowq,
    measure_audio_kbps,
    mp3_bitrate_for,
)

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def make_opus(tmp_path, kbps, seconds, title):
    out = tmp_path / "src.opus"
    subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "libopus", "-b:a", f"{kbps}k", "-vbr", "off", "-metadata", f"title={title}", str(out)],
        check=True, capture_output=True,
    )
    return out


def probe_tags(path):
    res = subprocess.run(
        [shutil.which("ffprobe"), "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return {k.lower(): v for k, v in json.loads(res.stdout)["format"]["tags"].items()}


@pytest.mark.parametrize(
    "src,expected",
    [(160, 224), (130, 192), (128, 160), (200, 256), (300, 256), (90, 128), (102.4, 128)],
)
def test_mp3_bitrate_for(src, expected):
    assert mp3_bitrate_for(src) == expected


def test_mp3_bitrate_rejects_zero():
    with pytest.raises(ValueError):
        mp3_bitrate_for(0)


@needs_ffmpeg
def test_measure_opus_160(tmp_path):
    src = make_opus(tmp_path, kbps=160, seconds=10, title="Song")
    assert 130 <= measure_audio_kbps(FFMPEG, src) <= 175


@needs_ffmpeg
def test_encode_writes_cbr_tags_and_lowq(tmp_path):
    src = make_opus(tmp_path, kbps=160, seconds=10, title="Song")
    out = tmp_path / "out.mp3"
    encode_mp3_lowq(FFMPEG, src, out, 224)
    tags = probe_tags(out)
    assert tags["title"] == "Song" and tags["comment"] == "lowq"
    assert 215 <= measure_audio_kbps(FFMPEG, out) <= 232


@needs_ffmpeg
def test_encode_cancel_removes_target(tmp_path):
    src = make_opus(tmp_path, kbps=160, seconds=10, title="Song")
    out = tmp_path / "out.mp3"
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(TranscodeError, match="cancelled"):
        encode_mp3_lowq(FFMPEG, src, out, 224, cancel)
    assert not out.exists()


@needs_ffmpeg
def test_encode_failure_raises_and_removes_target(tmp_path):
    bad = tmp_path / "bad.opus"
    bad.write_bytes(b"not audio")
    out = tmp_path / "out.mp3"
    with pytest.raises(TranscodeError):
        encode_mp3_lowq(FFMPEG, bad, out, 224)
    assert not out.exists()
