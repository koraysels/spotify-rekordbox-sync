"""Put every tag of a download into the ID3v2.3 frame players actually read.

ffmpeg writes only the text frames it has a name for. Anything else lands in a
TXXX ("user defined") frame that rekordbox and most players ignore: the
comment (so ``lowq`` would never reach rekordbox's Comments column), lyrics,
the Spotify URL, the ISRC, BPM, key, track and disc totals, and the label,
which spotDL writes as "encodedby". This rewrites those TXXX frames into the
proper ones, and marks the cover as the front cover.
"""

from __future__ import annotations

from pathlib import Path

# TXXX description (lowercase) -> text frame.
_TEXT_FRAMES = {
    "isrc": "TSRC",
    "bpm": "TBPM",
    "initialkey": "TKEY",
    "key": "TKEY",
    "encodedby": "TPUB",  # spotDL puts the record label here
    "publisher": "TPUB",
    "label": "TPUB",
    "organization": "TPUB",
    "copyright": "TCOP",
    "genre": "TCON",
}
_LYRICS = {"uslt", "lyrics", "unsyncedlyrics"}
_URL_FRAMES = {"woas": "WOAS"}
_TOTALS = {"tracktotal": "TRCK", "totaltracks": "TRCK", "disctotal": "TPOS", "totaldiscs": "TPOS"}
_LANGUAGE = b"eng"
_FRONT_COVER = 3


def _syncsafe(raw: bytes) -> int:
    value = 0
    for byte in raw:
        value = (value << 7) | (byte & 0x7F)
    return value


def _to_syncsafe(value: int) -> bytes:
    return bytes((value >> shift) & 0x7F for shift in (21, 14, 7, 0))


def _split_encoded(encoding: int, payload: bytes) -> tuple[str, str]:
    """A terminated string followed by the rest, both decoded."""
    if encoding in (1, 2):
        end = next((i for i in range(0, len(payload) - 1, 2) if payload[i:i + 2] == b"\0\0"), len(payload))
        first, rest = payload[:end], payload[end + 2:]
        codec = "utf-16" if encoding == 1 else "utf-16-be"
    else:
        end = payload.find(b"\0")
        end = len(payload) if end < 0 else end
        first, rest = payload[:end], payload[end + 1:]
        codec = "latin-1" if encoding == 0 else "utf-8"

    def decode(raw: bytes) -> str:
        return raw.decode(codec, "replace").lstrip("\ufeff").rstrip("\0")

    return decode(first), decode(rest)


def _text_value(body: bytes) -> str:
    """The text of a T*** frame body."""
    _, value = _split_encoded(body[0], _terminator(body[0]) + body[1:])
    return value


def _terminator(encoding: int) -> bytes:
    return b"\0\0" if encoding in (1, 2) else b"\0"


def _encode(text: str) -> tuple[bytes, bytes, bytes]:
    """(encoding byte, encoded text, string terminator) for an ID3v2.3 string."""
    try:
        return b"\0", text.encode("latin-1"), b"\0"
    except UnicodeEncodeError:
        return b"\1", text.encode("utf-16"), b"\0\0"


def text_frame(value: str) -> bytes:
    encoding, data, _ = _encode(value)
    return encoding + data


def language_frame(value: str) -> bytes:
    """COMM / USLT body: language, an empty description, then the text."""
    encoding, data, terminator = _encode(value)
    empty = b"" if encoding == b"\0" else "".encode("utf-16")
    return encoding + _LANGUAGE + empty + terminator + data


def read_frames(data: bytes) -> tuple[list[tuple[str, bytes, bytes]], int] | None:
    """(frames as (id, flags, body), tag length) of a plain ID3v2.3 tag, else None."""
    if len(data) < 10 or data[:3] != b"ID3" or data[3] != 3 or data[5] & 0xC0:
        return None  # not v2.3, or unsynchronised / extended header: leave it alone
    end = 10 + _syncsafe(data[6:10])
    frames = []
    pos = 10
    while pos + 10 <= end and data[pos:pos + 4].strip(b"\0"):
        size = int.from_bytes(data[pos + 4:pos + 8], "big")
        frames.append((data[pos:pos + 4].decode("latin-1"), data[pos + 8:pos + 10], data[pos + 10:pos + 10 + size]))
        pos += 10 + size
    return frames, end


def fix_tag(path: Path, *, override: dict[str, str] | None = None, fill: dict[str, str] | None = None) -> None:
    """Rewrite misplaced TXXX frames of ``path`` into proper frames.

    ``override`` sets text frames whatever the file says (rbsync's own Spotify
    data); ``fill`` sets them only where the file has none. Empty values are
    ignored.
    """
    data = path.read_bytes()
    parsed = read_frames(data)
    if parsed is None:
        return
    frames, end = parsed

    kept: list[tuple[str, bytes, bytes]] = []
    moved: dict[str, bytes] = {}  # frame id -> body, first one wins
    totals: dict[str, str] = {}
    for frame_id, flags, body in frames:
        if frame_id != "TXXX" or not body:
            kept.append((frame_id, flags, body))
            continue
        desc, value = _split_encoded(body[0], body[1:])
        key = desc.lower()
        if key in _TEXT_FRAMES:
            moved.setdefault(_TEXT_FRAMES[key], text_frame(value))
        elif key == "comment":
            moved.setdefault("COMM", language_frame(value))
        elif key in _LYRICS:
            moved.setdefault("USLT", language_frame(value))
        elif key in _URL_FRAMES:
            moved.setdefault(_URL_FRAMES[key], value.encode("latin-1", "replace"))
        elif key in _TOTALS:
            totals.setdefault(_TOTALS[key], value)
        else:
            kept.append((frame_id, flags, body))

    present = {frame_id for frame_id, _, _ in kept}
    for frame_id, body in moved.items():
        if frame_id not in present:
            kept.append((frame_id, b"\0\0", body))
            present.add(frame_id)
    for frame_id, value in (fill or {}).items():
        if value and frame_id not in present:
            kept.append((frame_id, b"\0\0", text_frame(value)))
            present.add(frame_id)
    for frame_id, value in (override or {}).items():
        if value:
            kept = [f for f in kept if f[0] != frame_id] + [(frame_id, b"\0\0", text_frame(value))]

    out = []
    for frame_id, flags, body in kept:
        if frame_id in totals and body:
            number = _text_value(body)
            if number and "/" not in number:
                body = text_frame(f"{number}/{totals[frame_id]}")
        elif frame_id == "APIC":
            body = _front_cover(body)
        out.append((frame_id, flags, body))
    # Pictures last, so the small frames are read first.
    out.sort(key=lambda f: f[0] == "APIC")

    payload = b"".join(fid.encode("latin-1") + len(body).to_bytes(4, "big") + flags + body for fid, flags, body in out)
    header = b"ID3\x03\x00\x00" + _to_syncsafe(len(payload))
    path.write_bytes(header + payload + data[end:])


def _front_cover(body: bytes) -> bytes:
    """Mark an "Other" picture (ffmpeg's default) as the front cover."""
    mime_end = body.find(b"\0", 1)
    if mime_end < 0 or mime_end + 1 >= len(body) or body[mime_end + 1] != 0:
        return body
    return body[:mime_end + 1] + bytes([_FRONT_COVER]) + body[mime_end + 2:]
