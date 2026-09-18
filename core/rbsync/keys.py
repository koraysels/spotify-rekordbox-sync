"""Musical keys in Camelot notation.

DJs read keys as Camelot ("8A"), because neighbouring numbers mix. rekordbox
writes whichever notation its preferences are set to, and Spotify gives a pitch
class plus a mode, so both are converted here and the app shows one notation.
"""

from __future__ import annotations

import re

# Pitch class (0 = C) to Camelot, major then minor.
_MAJOR = ["8B", "3B", "10B", "5B", "12B", "7B", "2B", "9B", "4B", "11B", "6B", "1B"]
_MINOR = ["5A", "12A", "7A", "2A", "9A", "4A", "11A", "6A", "1A", "8A", "3A", "10A"]

_PITCH = {
    "c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3, "e": 4, "fb": 4,
    "f": 5, "e#": 5, "f#": 6, "gb": 6, "g": 7, "g#": 8, "ab": 8, "a": 9,
    "a#": 10, "bb": 10, "b": 11, "cb": 11,
}

_CAMELOT = re.compile(r"^\s*(1[0-2]|[1-9])\s*([ab])\s*$", re.IGNORECASE)
_NAME = re.compile(
    r"^\s*([a-g])\s*([#♯b♭]?)\s*(m|min|minor|maj|major)?\s*$", re.IGNORECASE
)


def camelot_from_pitch(pitch: int | None, mode: int | None) -> str:
    """Camelot for Spotify's key (0..11, C = 0) and mode (1 major, 0 minor)."""
    if pitch is None or mode is None or not 0 <= int(pitch) <= 11:
        return ""
    return (_MAJOR if int(mode) == 1 else _MINOR)[int(pitch)]


def to_camelot(key: str) -> str:
    """Convert a key name to Camelot, or return it unchanged when unrecognised.

    Handles "Am", "A min", "Bbm", "F#", and passes existing Camelot through. An
    unknown value is kept rather than blanked: showing the user's own notation
    beats showing nothing.
    """
    text = (key or "").strip()
    if not text:
        return ""

    camelot = _CAMELOT.match(text)
    if camelot:
        return f"{int(camelot.group(1))}{camelot.group(2).upper()}"

    name = _NAME.match(text)
    if not name:
        return text
    accidental = name.group(2).replace("♯", "#").replace("♭", "b")
    pitch = _PITCH.get(f"{name.group(1).lower()}{accidental.lower()}")
    if pitch is None:
        return text
    quality = (name.group(3) or "").lower()
    return camelot_from_pitch(pitch, 0 if quality.startswith("m") and not quality.startswith("maj") else 1)
