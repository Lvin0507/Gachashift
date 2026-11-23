"""Ask GitHub whether a newer release is out. Only reads the public releases list."""

import re
from dataclasses import dataclass

import requests

from . import __version__

REPO = "Lvin0507/Gachashift"
RELEASES = f"https://github.com/{REPO}/releases/latest"
ZIP_NAME = re.compile(r"^Gachashift-\d+\.\d+\.\d+\.zip$")


@dataclass
class Release:
    version: str          # "1.2.0"
    page: str             # the release page, for the notes and a manual download
    zip_url: str = ""     # the zip to install, if the release has one
    zip_size: int = 0
    sha256: str = ""      # from GitHub's own digest of the zip, if it gives one
    sha256_url: str = ""  # or the .sha256 file published next to the zip


def _parts(version):
    """'v1.10.2' -> (1, 10, 2), so versions compare as numbers, not text."""
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def release_from(data):
    """A Release from GitHub's JSON for one release."""
    rel = Release(version=data.get("tag_name", "").lstrip("v"), page=data.get("html_url") or RELEASES)
    assets = {a.get("name", ""): a for a in data.get("assets") or []}
    for name, asset in assets.items():
        if ZIP_NAME.match(name):
            rel.zip_url = asset.get("browser_download_url", "")
            rel.zip_size = int(asset.get("size") or 0)
            digest = asset.get("digest") or ""
            if digest.startswith("sha256:"):
                rel.sha256 = digest.split(":", 1)[1].lower()
            rel.sha256_url = (assets.get(name + ".sha256") or {}).get("browser_download_url", "")
            break
    return rel


def newer_release(timeout=8):
    """The latest Release if it is newer than this program, or None (also when offline)."""
    try:
        r = requests.get(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=timeout,
                         headers={"Accept": "application/vnd.github+json"})
        if not r.ok:
            return None
        rel = release_from(r.json())
        if rel.version and _parts(rel.version) > _parts(__version__):
            return rel
    except (requests.exceptions.RequestException, ValueError):
        pass
    return None
