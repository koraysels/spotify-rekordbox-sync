from rbsync.id3 import fix_tag, read_frames
from rbsync.keys import key_name

AUDIO = b"\xff\xfb\x90\x00" + b"\x01" * 64


def frame(fid: str, body: bytes) -> bytes:
    return fid.encode() + len(body).to_bytes(4, "big") + b"\0\0" + body


def txxx(desc: str, value: str, utf16: bool = False) -> bytes:
    if utf16:
        return frame("TXXX", b"\1" + desc.encode("utf-16") + b"\0\0" + value.encode("utf-16") + b"\0\0")
    return frame("TXXX", b"\0" + desc.encode("latin-1") + b"\0" + value.encode("latin-1") + b"\0")


def tag(*frames: bytes, version: int = 3) -> bytes:
    body = b"".join(frames) + b"\0" * 10  # ffmpeg pads its tag
    size = len(body)
    syncsafe = bytes((size >> s) & 0x7F for s in (21, 14, 7, 0))
    return b"ID3" + bytes([version, 0, 0]) + syncsafe + body


def texts(data: bytes) -> dict[str, bytes]:
    frames, _ = read_frames(data)
    return {fid: body for fid, _, body in frames}


def test_key_name():
    assert key_name(9, 0) == "Am" and key_name(6, 1) == "F#" and key_name(0, 1) == "C"
    assert key_name(-1, 1) == "" and key_name(None, 0) == "" and key_name(3, None) == ""


def test_txxx_frames_move_to_their_proper_frames(tmp_path):
    path = tmp_path / "x.mp3"
    path.write_bytes(tag(
        frame("TRCK", b"\x003\0"),
        txxx("tracktotal", "10"),
        txxx("comment", "lowq"),
        txxx("ISRC", "GBAYE0601498", utf16=True),
        txxx("encodedby", "Label"),
        txxx("woas", "https://open.spotify.com/track/abc"),
        txxx("USLT", "line one\nline two"),
        txxx("mood", "dark"),
    ) + AUDIO)

    fix_tag(path)

    data = path.read_bytes()
    frames = texts(data)
    assert frames["TRCK"] == b"\x003/10"
    assert frames["COMM"] == b"\x00eng\x00lowq"
    assert frames["TSRC"] == b"\x00GBAYE0601498"
    assert frames["TPUB"] == b"\x00Label"
    assert frames["WOAS"] == b"https://open.spotify.com/track/abc"
    assert frames["USLT"] == b"\x00eng\x00line one\nline two"
    assert frames["TXXX"] == b"\x00mood\x00dark\x00"  # unknown ones stay as they were
    assert data.endswith(AUDIO)


def test_override_replaces_and_fill_only_adds(tmp_path):
    path = tmp_path / "x.mp3"
    path.write_bytes(tag(txxx("isrc", "FROMSOURCE01"), frame("TBPM", b"\x00128")) + AUDIO)

    fix_tag(path, override={"TSRC": "USRC17607839"}, fill={"TBPM": "124", "TKEY": "Am"})

    frames = texts(path.read_bytes())
    assert frames["TSRC"] == b"\x00USRC17607839"
    assert frames["TBPM"] == b"\x00128" and frames["TKEY"] == b"\x00Am"


def test_empty_values_write_no_frame(tmp_path):
    path = tmp_path / "x.mp3"
    path.write_bytes(tag(frame("TIT2", b"\x00Song")) + AUDIO)
    fix_tag(path, override={"TSRC": ""}, fill={"TKEY": ""})
    assert set(texts(path.read_bytes())) == {"TIT2"}


def test_non_ascii_text_is_written_as_utf16(tmp_path):
    path = tmp_path / "x.mp3"
    path.write_bytes(tag(txxx("encodedby", "Łabel", utf16=True)) + AUDIO)
    fix_tag(path)
    body = texts(path.read_bytes())["TPUB"]
    assert body[:1] == b"\1" and body[1:].decode("utf-16") == "Łabel"


def test_ffmpeg_other_picture_becomes_front_cover(tmp_path):
    path = tmp_path / "x.mp3"
    path.write_bytes(tag(frame("APIC", b"\x00image/jpeg\x00\x00\x00JPEGDATA"), frame("TIT2", b"\x00Song")) + AUDIO)
    fix_tag(path)
    frames, _ = read_frames(path.read_bytes())
    assert [fid for fid, _, _ in frames] == ["TIT2", "APIC"]
    assert frames[1][2] == b"\x00image/jpeg\x00\x03\x00JPEGDATA"


def test_other_tag_versions_are_left_alone(tmp_path):
    path = tmp_path / "x.mp3"
    original = tag(txxx("comment", "lowq"), version=4) + AUDIO
    path.write_bytes(original)
    fix_tag(path)
    assert path.read_bytes() == original
