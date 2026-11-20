import base64
import json
import shutil
import struct
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


def id3_frames(path):
    """ID3v2.3 frames of ``path`` as {frame id: [decoded text, ...]}; written
    independently of rbsync.id3 so the two cannot share a mistake."""
    data = path.read_bytes()
    assert data[:3] == b"ID3" and data[3] == 3, "expected an ID3v2.3 tag"
    end = 10 + sum((b & 0x7F) << (7 * (3 - i)) for i, b in enumerate(data[6:10]))
    frames, pos = {}, 10
    while pos + 10 <= end and data[pos:pos + 4] != b"\0\0\0\0":
        fid = data[pos:pos + 4].decode()
        size = int.from_bytes(data[pos + 4:pos + 8], "big")
        body = data[pos + 10:pos + 10 + size]
        pos += 10 + size
        if fid == "APIC":
            mime_end = body.index(b"\0", 1)
            text = f"type={body[mime_end + 1]} mime={body[1:mime_end].decode()}"
        elif fid.startswith("W") and fid != "WXXX":
            text = body.decode("latin-1")
        else:
            codec = {0: "latin-1", 1: "utf-16", 3: "utf-8"}[body[0]]
            raw = body[4:] if fid in ("COMM", "USLT") else body[1:]
            if fid in ("COMM", "USLT", "TXXX"):  # skip the description
                term = b"\0\0" if body[0] == 1 else b"\0"
                cut = next(i for i in range(0, len(raw), len(term)) if raw[i:i + len(term)] == term)
                raw = raw[cut + len(term):]
            text = raw.decode(codec).lstrip("\ufeff").rstrip("\0")
        frames.setdefault(fid, []).append(text)
    return frames


def make_tagged_opus(tmp_path):
    """An Opus file tagged the way spotDL tags one: Vorbis comments on the
    stream (not the file) and the cover as METADATA_BLOCK_PICTURE."""
    cover = tmp_path / "cover.jpg"
    subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-f", "lavfi", "-i", "color=c=red:s=16x16", "-frames:v", "1", str(cover)],
        check=True, capture_output=True,
    )
    jpeg, mime, desc = cover.read_bytes(), b"image/jpeg", b"Cover (front)"
    picture = (
        struct.pack(">II", 3, len(mime)) + mime + struct.pack(">I", len(desc)) + desc
        + struct.pack(">IIIII", 16, 16, 24, 0, len(jpeg)) + jpeg
    )
    tags = {
        "title": "Song", "artist": "Ärtist", "album_artist": "Ärtist", "album": "Album",
        "date": "2024-05-01", "track": "3", "tracktotal": "10", "disc": "1", "disctotal": "2",
        "genre": "Techno", "copyright": "2024 Label", "encodedby": "Label",
        "isrc": "GBAYE0601498", "lyrics": "line one\nline two",
        "woas": "https://open.spotify.com/track/abc", "comment": "https://music.youtube.com/watch?v=x",
        "METADATA_BLOCK_PICTURE": base64.b64encode(picture).decode(),
    }
    out = tmp_path / "tagged.opus"
    cmd = [FFMPEG, "-y", "-hide_banner", "-f", "lavfi", "-i", "sine=duration=2", "-c:a", "libopus"]
    for key, value in tags.items():
        cmd += ["-metadata", f"{key}={value}"]
    subprocess.run(cmd + [str(out)], check=True, capture_output=True)
    return out


@needs_ffmpeg
def test_encode_puts_every_spotdl_tag_in_its_id3_frame(tmp_path):
    out = tmp_path / "out.mp3"
    encode_mp3_lowq(FFMPEG, make_tagged_opus(tmp_path), out, 128)
    frames = id3_frames(out)

    assert frames["TIT2"] == ["Song"] and frames["TPE1"] == ["Ärtist"] and frames["TPE2"] == ["Ärtist"]
    assert frames["TALB"] == ["Album"] and frames["TYER"] == ["2024"]
    assert frames["TRCK"] == ["3/10"] and frames["TPOS"] == ["1/2"]
    assert frames["TCON"] == ["Techno"] and frames["TCOP"] == ["2024 Label"] and frames["TPUB"] == ["Label"]
    assert frames["TSRC"] == ["GBAYE0601498"]
    assert frames["USLT"] == ["line one\nline two"]
    assert frames["WOAS"] == ["https://open.spotify.com/track/abc"]
    assert frames["COMM"] == ["lowq"]
    assert frames["APIC"] == ["type=3 mime=image/jpeg"]
    assert "TXXX" not in frames, frames.get("TXXX")
    assert probe_tags(out)["comment"] == "lowq"


@needs_ffmpeg
def test_encode_prefers_spotify_isrc_and_fills_bpm_and_key(tmp_path):
    out = tmp_path / "out.mp3"
    encode_mp3_lowq(
        FFMPEG, make_tagged_opus(tmp_path), out, 128,
        isrc="USRC17607839", fill={"TBPM": "124", "TKEY": "Am"},
    )
    frames = id3_frames(out)
    assert frames["TSRC"] == ["USRC17607839"]
    assert frames["TBPM"] == ["124"] and frames["TKEY"] == ["Am"]


@needs_ffmpeg
def test_encode_without_isrc_anywhere_writes_no_tsrc(tmp_path):
    src = make_opus(tmp_path, kbps=96, seconds=2, title="Song")
    out = tmp_path / "out.mp3"
    encode_mp3_lowq(FFMPEG, src, out, 128, isrc="")
    frames = id3_frames(out)
    assert "TSRC" not in frames and frames["COMM"] == ["lowq"] and frames["TIT2"] == ["Song"]
