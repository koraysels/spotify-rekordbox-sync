"""Locating and installing the external tools the downloader needs.

spotDL does the downloading and ffmpeg does the conversion. Neither ships with
the app, so we look in the places a user is likely to have them and, for spotDL,
can fetch a pinned, checksum-verified release binary.
"""

from __future__ import annotations

import glob
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

import httpx

SPOTDL_VERSION = "4.6.0"
FFMPEG_TIMEOUT = 300.0  # seconds; it runs on the download worker, so it must end
_RELEASE_URL = "https://github.com/spotDL/spotify-downloader/releases/download/v{v}/{asset}"

# (sys.platform, machine) -> (release asset name, sha256)
SPOTDL_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("darwin", "arm64"): (
        "spotdl-4.6.0-darwin",
        "957bb335e773ab67fc7a65574b0465ad828849944025a84cdfc9466a4336e3bb",
    ),
    ("win32", "AMD64"): (
        "spotdl-4.6.0-win32.exe",
        "e674030c3337cd74120a3a086887ce1a5195765cfc17e1971a2807e0a398b505",
    ),
    ("linux", "x86_64"): (
        "spotdl-4.6.0-linux",
        "99eb14032e252af30f1c6bdc7461057c324754978afe30c6583ed6b3ec3257bf",
    ),
}


class ToolMissing(RuntimeError):
    pass


class InstallError(RuntimeError):
    pass


def asset_for(system: str, machine: str) -> tuple[str, str] | None:
    return SPOTDL_ASSETS.get((system, machine))


def known_dirs(home: Path | None = None) -> list[Path]:
    """Install locations a GUI app's minimal PATH tends to miss."""
    home = home or Path.home()
    dirs = [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), home / ".local" / "bin"]
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        pattern = os.path.join(glob.escape(local), "Programs", "Python", "*", "Scripts")
        dirs.extend(Path(p) for p in sorted(glob.glob(pattern)))
    return dirs


def _which(name: str, directories: list[Path]) -> str | None:
    return shutil.which(name, path=os.pathsep.join(str(d) for d in directories))


def _is_executable(path: str) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def find_spotdl(
    setting_path: str,
    tools_dir: Path,
    env_path: str | None = None,
    extra_dirs: list[Path] | None = None,
) -> tuple[str | None, str]:
    """Return (path, source); source is setting, installed, path, known or ''."""
    if _is_executable(setting_path):
        return setting_path, "setting"
    asset = asset_for(sys.platform, platform.machine())
    if asset:
        installed = tools_dir / asset[0]
        if _is_executable(str(installed)):
            return str(installed), "installed"
    on_path = shutil.which("spotdl", path=env_path)
    if on_path:
        return on_path, "path"
    known = _which("spotdl", known_dirs() if extra_dirs is None else extra_dirs)
    if known:
        return known, "known"
    return None, ""


def find_ffmpeg(
    env_path: str | None = None,
    extra_dirs: list[Path] | None = None,
    home: Path | None = None,
) -> str | None:
    on_path = shutil.which("ffmpeg", path=env_path)
    if on_path:
        return on_path
    known = _which("ffmpeg", known_dirs(home) if extra_dirs is None else extra_dirs)
    if known:
        return known
    # spotDL's own `--download-ffmpeg` puts a copy here.
    return _which("ffmpeg", [(home or Path.home()) / ".spotdl"])


def http_fetch(url: str, dest: Path) -> None:
    with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
        response.raise_for_status()
        with open(dest, "wb") as out:
            for chunk in response.iter_bytes():
                out.write(chunk)


def install_spotdl(
    tools_dir: Path,
    fetch: Callable[[str, Path], None],
    system: str = sys.platform,
    machine: str = platform.machine(),
) -> Path:
    asset = asset_for(system, machine)
    if asset is None:
        raise InstallError(
            f"No prebuilt spotDL for {system}/{machine}. Install it yourself with "
            "`pipx install spotdl` or `brew install spotdl`, then set the spotDL "
            "path in settings."
        )
    name, expected = asset
    tools_dir.mkdir(parents=True, exist_ok=True)
    dest = tools_dir / name
    part = tools_dir / (name + ".part")
    try:
        fetch(_RELEASE_URL.format(v=SPOTDL_VERSION, asset=name), part)
        hasher = hashlib.sha256()
        with open(part, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(chunk)
        if hasher.hexdigest() != expected:
            raise InstallError(f"checksum mismatch for {name}; download discarded")
        part.replace(dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    dest.chmod(0o755)
    if system == "darwin":
        try:
            subprocess.run(
                ["xattr", "-d", "com.apple.quarantine", str(dest)],
                capture_output=True,
                check=False,
            )
        except OSError:
            pass
    return dest


def last_line(output: str) -> str:
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def download_ffmpeg(
    spotdl: str,
    run: Callable[[list[str], threading.Event], tuple[int, str]],
    timeout: float = FFMPEG_TIMEOUT,
) -> str:
    """Have spotDL fetch ffmpeg into ~/.spotdl, and return where it landed.

    ``run`` is the downloader's process runner, which kills spotDL and its
    children once the event is set; the timer sets it after ``timeout``.
    """
    expired = threading.Event()
    timer = threading.Timer(timeout, expired.set)
    timer.daemon = True
    timer.start()
    try:
        rc, out = run([spotdl, "--download-ffmpeg"], expired)
    finally:
        timer.cancel()
    found = find_ffmpeg()
    if found:
        return found
    if expired.is_set():
        raise InstallError(f"Downloading ffmpeg timed out after {round(timeout)} s.")
    detail = last_line(out) or f"spotDL exited {rc}"
    raise InstallError(f"ffmpeg could not be downloaded: {detail}")
