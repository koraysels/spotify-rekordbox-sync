"""Text normalization for matching Spotify tracks against a rekordbox collection.

The rules here are derived from the user's actual library, not from theory.
A survey of 12,630 rekordbox rows showed titles carrying noise such as
``(Original Version)``, ``(OFFICIAL SONG)`` and ``[Prod. By Sonny Digital]``,
and artist fields packing collaborators inline (``Wiz Khalifa Ft. Travis Scott``).
Matching without stripping these produces false negatives on tracks the user
plainly owns.
"""

from __future__ import annotations

import re
import unicodedata

# Bracketed groups whose contents match any of these are dropped entirely.
# Anything else in brackets is kept, because it usually carries real meaning
# ("Deadmau5 Remix" distinguishes a track; "Official Video" does not).
_NOISE_GROUP = re.compile(
    r"""^(?:
        (?:the\s+)?original\s+(?:version|mix|edit)
      | official\s+(?:song|video|audio|music\s+video|lyric\s+video)
      | (?:prod|pro)\.?\s*(?:by)?\s+.*
      | (?:feat|ft)\.?\s+.*
      | hq | hd | free\s+download
    )$""",
    re.VERBOSE,
)

_BRACKETS = re.compile(r"\(([^()]*)\)|\[([^\[\]]*)\]")
_TRAILING_FEAT = re.compile(r"\b(?:feat|ft)\.?\s+.*$")
# Two-digit prefixes are file track numbers ("03 Versace"). A single digit is
# far more likely to belong to the title ("7 Rings"), so it is left alone.
_TRACK_NUMBER = re.compile(r"^\d{2}\s+")
_APOSTROPHES = re.compile(r"['’ʼ`]")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")
_LEADING_THE = re.compile(r"^the\s+")

_ARTIST_SEPARATORS = re.compile(
    r"\s*(?:&|,|/|\+|\bfeat\b|\bft\b|\bvs\b|\bversus\b|\bx\b|\bwith\b|\band\b)\s*"
)

_MIX_TAGS = {
    "remix": re.compile(r"\bremix(?:es)?\b"),
    "extended": re.compile(r"\bextended\b"),
    "radio": re.compile(r"\bradio\b"),
    "live": re.compile(r"\blive\b"),
    "dub": re.compile(r"\bdub\b"),
    "acoustic": re.compile(r"\bacoustic\b"),
    "instrumental": re.compile(r"\binstrumental\b"),
    "edit": re.compile(r"\bedit\b"),
    "bootleg": re.compile(r"\bbootleg\b"),
    "vip": re.compile(r"\bvip\b"),
}


def _fold(text: str | None) -> str:
    """Lowercase and strip diacritics, leaving punctuation intact."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.lower().strip()


def _depunctuate(text: str) -> str:
    """Drop apostrophes without splitting words, turn other punctuation into space."""
    text = _APOSTROPHES.sub("", text)
    text = _NON_WORD.sub(" ", text)
    return _WS.sub(" ", text).strip()


def _strip_bracket_noise(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        inner = (match.group(1) if match.group(1) is not None else match.group(2)) or ""
        inner = inner.strip()
        if _NOISE_GROUP.match(inner):
            return " "
        return f" {inner} "

    previous = None
    # Loop to handle nesting, which single-pass regex cannot reach.
    while previous != text:
        previous = text
        text = _BRACKETS.sub(replace, text)
    return text


def normalize_title(title: str | None) -> str:
    """Reduce a track title to its comparable core."""
    text = _fold(title)
    if not text:
        return ""
    text = _strip_bracket_noise(text)
    text = _TRAILING_FEAT.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    text = _TRACK_NUMBER.sub("", text)
    return _depunctuate(text)


def normalize_artist(artist: str | None) -> str:
    """Reduce a single artist name to its comparable core."""
    text = _fold(artist)
    if not text:
        return ""
    text = _depunctuate(text)
    return _LEADING_THE.sub("", text).strip()


def split_artists(artists: str | None) -> list[str]:
    """Split a packed artist field into individual normalized artist names.

    Rekordbox stores collaborators inconsistently, so ``"Kool John & P-Lo"``
    and ``"Wiz Khalifa Ft. Travis Scott"`` must both yield two artists.
    """
    text = _fold(artists)
    if not text:
        return []
    text = _APOSTROPHES.sub("", text)
    # Preserve the separator characters while turning other punctuation to space.
    text = re.sub(r"[^\w\s&,/+]", " ", text)
    text = _WS.sub(" ", text)

    parts = _ARTIST_SEPARATORS.split(text)
    out: list[str] = []
    for part in parts:
        cleaned = _depunctuate(part)
        cleaned = _LEADING_THE.sub("", cleaned).strip()
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def extract_mix_tags(title: str | None) -> set[str]:
    """Return the mix descriptors present in a title.

    Used as a guard: a radio edit and an extended mix share a title and artist
    but are different records, and swapping one for the other in a DJ set is a
    real failure.
    """
    text = _fold(title)
    if not text:
        return set()
    text = _depunctuate(text)
    return {tag for tag, pattern in _MIX_TAGS.items() if pattern.search(text)}
