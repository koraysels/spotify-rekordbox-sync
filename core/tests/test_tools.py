import hashlib
import os
from pathlib import Path

import pytest

from rbsync.tools import (
    SPOTDL_ASSETS,
    InstallError,
    asset_for,
    find_ffmpeg,
    find_spotdl,
    install_spotdl,
)


def make_exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_asset_for_known_and_unknown():
    assert asset_for("darwin", "arm64")[0] == "spotdl-4.6.0-darwin"
    assert asset_for("win32", "AMD64")[0] == "spotdl-4.6.0-win32.exe"
    assert asset_for("darwin", "x86_64") is None


def test_install_verifies_hash_and_deletes_on_mismatch(tmp_path):
    def fetch(url, dest):
        dest.write_bytes(b"not spotdl")

    with pytest.raises(InstallError, match="checksum"):
        install_spotdl(tmp_path, fetch, "darwin", "arm64")
    assert list(tmp_path.iterdir()) == []


def test_install_success_is_executable(tmp_path, monkeypatch):
    payload = b"fake"
    monkeypatch.setitem(
        SPOTDL_ASSETS,
        ("darwin", "arm64"),
        ("spotdl-4.6.0-darwin", hashlib.sha256(payload).hexdigest()),
    )
    path = install_spotdl(tmp_path, lambda url, dest: dest.write_bytes(payload), "darwin", "arm64")
    assert path == tmp_path / "spotdl-4.6.0-darwin"
    assert os.access(path, os.X_OK)


def test_install_without_asset_raises_with_instructions(tmp_path):
    with pytest.raises(InstallError, match="pipx install spotdl"):
        install_spotdl(tmp_path, lambda u, d: None, "darwin", "x86_64")


def test_find_spotdl_order(tmp_path):
    # setting beats installed beats PATH beats known dirs
    import platform
    import sys

    tools = tmp_path / "tools"
    name = asset_for(sys.platform, platform.machine())
    installed_name = name[0] if name else "spotdl-installed"
    setting_bin = make_exe(tmp_path / "mine" / "spotdl")
    installed = make_exe(tools / installed_name)
    path_dir = tmp_path / "bin"
    make_exe(path_dir / "spotdl")
    make_exe(path_dir / "spotdl.exe")

    assert find_spotdl(str(setting_bin), tools, env_path=str(path_dir))[1] == "setting"
    if name:
        assert find_spotdl("", tools, env_path=str(path_dir)) == (str(installed), "installed")
    found = find_spotdl("", tmp_path / "none", env_path=str(path_dir))
    assert found[1] == "path"
    assert find_spotdl("", tmp_path / "none", env_path="", extra_dirs=[])[1] in ("known", "")


def test_find_spotdl_in_known_dir_when_path_is_minimal(tmp_path):
    brew = tmp_path / "brew"
    make_exe(brew / "spotdl")
    assert find_spotdl("", tmp_path / "empty", env_path="/usr/bin", extra_dirs=[brew]) == (
        str(brew / "spotdl"),
        "known",
    )


def test_find_ffmpeg_uses_spotdl_copy(tmp_path):
    make_exe(tmp_path / ".spotdl" / "ffmpeg")
    assert find_ffmpeg(env_path="", extra_dirs=[], home=tmp_path).endswith("ffmpeg")
