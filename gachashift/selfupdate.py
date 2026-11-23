"""Install a newer release with one click (the packaged exe only).

The zip is downloaded and checked against the SHA-256 GitHub publishes for it, then unpacked
next to the program. A program can't replace its own running files, so a small script waits
for the app to close, copies the new files over the old ones (config.json, logs and the
other files a run leaves are never touched), and opens the app again."""

import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

from .config import app_dir

ALLOWED_HOSTS = ("https://github.com/", "https://objects.githubusercontent.com/",
                 "https://release-assets.githubusercontent.com/")


class UpdateError(Exception):
    """Something stopped the update; the message says what, and nothing was changed."""


def can_self_update():
    """Only the packaged Gachashift.exe can replace itself; from source, git pull does it."""
    return bool(getattr(sys, "frozen", False))


def expected_sha256(release, timeout=15):
    """The zip's SHA-256: GitHub's own digest, else the .sha256 file next to the zip."""
    if release.sha256:
        return release.sha256
    if release.sha256_url:
        r = requests.get(release.sha256_url, timeout=timeout)
        if r.ok and r.text.split():
            return r.text.split()[0].strip().lower()
    return ""


def download(release, dest, progress=None, timeout=30):
    """Download the release zip to dest and check it. Raises UpdateError."""
    if not release.zip_url.startswith(ALLOWED_HOSTS):
        raise UpdateError(f"unexpected download address: {release.zip_url}")
    want = expected_sha256(release)
    if not want:
        raise UpdateError("the release has no checksum to verify the download against")
    digest, done = hashlib.sha256(), 0
    try:
        with requests.get(release.zip_url, stream=True, timeout=timeout) as r, open(dest, "wb") as f:
            r.raise_for_status()
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress and release.zip_size:
                    progress(min(100, done * 100 // release.zip_size))
    except requests.exceptions.RequestException as e:
        raise UpdateError(f"download failed: {type(e).__name__}") from e
    if digest.hexdigest() != want:
        os.remove(dest)
        raise UpdateError("the download doesn't match its checksum, so it was thrown away")
    return dest


def unpack(zip_path, staging):
    """Unpack into staging and return the folder holding Gachashift.exe. Refuses entries that
    would land outside staging."""
    staging = Path(staging).resolve()
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            target = (staging / name).resolve()
            if staging not in target.parents and target != staging:
                raise UpdateError(f"unsafe path in the zip: {name}")
        z.extractall(staging)
    for folder in (staging / "Gachashift", staging):
        # the updater mirrors _internal, so it must be there and complete
        if (folder / "Gachashift.exe").exists() and (folder / "_internal").is_dir():
            return folder
    raise UpdateError("the download doesn't contain a complete Gachashift")


def updater_script(new_files, install_dir, pid, log, staging):
    """The batch file that waits for the app to close, copies the new version over the old
    one and starts it again. _internal is mirrored (old library files go); everything else
    is copied over, so settings, logs and anything a run leaves stay as they are. Last, it
    removes the download folder, itself included."""
    new_files, install_dir = str(new_files), str(install_dir)
    copy = "/R:5 /W:2 /NP /NFL /NDL"
    return "\r\n".join([
        "@echo off",
        "chcp 65001 >nul",
        "rem Gachashift updater: waits for the app to close, then installs the new version.",
        ":wait",
        # ping waits about a second and, unlike timeout, works without a visible console
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul && (ping -n 2 127.0.0.1 >nul & goto wait)',
        f'robocopy "{new_files}\\_internal" "{install_dir}\\_internal" /MIR {copy} >>"{log}"',
        f'robocopy "{new_files}" "{install_dir}" /E /XD "{new_files}\\_internal" /XF config.json {copy} >>"{log}"',
        f'start "" "{install_dir}\\Gachashift.exe"',
        f'(goto) 2>nul & rmdir /s /q "{staging}"',
        "",
    ])


def prepare(release, progress=None):
    """Download, check and unpack the release, and write the updater script. Returns the
    script's path; run it with start_updater() and then close the app."""
    install = app_dir()
    staging = Path(tempfile.mkdtemp(prefix="gachashift-update-"))
    zip_path = staging / "update.zip"
    download(release, zip_path, progress)
    new_files = unpack(zip_path, staging / "files")
    os.remove(zip_path)
    (install / "logs").mkdir(exist_ok=True)
    script = staging / "install-update.cmd"
    script.write_text(updater_script(new_files, install, os.getpid(), install / "logs" / "update.log",
                                     staging), encoding="utf-8")
    return script


def start_updater(script):
    """Start the script in a hidden window. It isn't tied to the app, so it keeps running
    after the app closes."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=flags, close_fds=True)
