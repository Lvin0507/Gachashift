"""Find where each game's tool is installed, so the setup doesn't start with six Browse
buttons. Looks at tools that are running first (exact), then searches the usual places a
few folders deep, within a time limit. Only fills settings that are empty or point to a
file that no longer exists."""

import os
import re
import string
import time
from pathlib import Path

import psutil

# game id -> (setting, file name or pattern). The other settings follow from these.
TARGETS = {
    "endfield": [("maaend_path", "MaaEnd.exe")],
    "arknights": [("maa_path", "MAA.exe")],
    "wuthering": [("okww_path", "ok-ww.exe")],
    "bluearchive": [("baas_exe", re.compile(r"^BlueArchiveAutoScript.*\.exe$", re.I)),
                    ("launcher_path", "BlueArchive_JP_Gamelauncher.exe")],
    "zzz": [("od_dir", "OneDragon-Launcher.exe")],
    "genshin": [("bgi_path", "BetterGI.exe")],
}
# Each game's own exe, kept as game_path (the tools' settings can be fixed to point at it)
GAMES = {
    "endfield": "Endfield.exe",
    "arknights": "Arknights.exe",
    "wuthering": "Client-Win64-Shipping.exe",
    "bluearchive": "BlueArchive.exe",
    "zzz": "ZenlessZoneZero.exe",
    "genshin": re.compile(r"^(GenshinImpact|YuanShen)\.exe$", re.I),
}
for _gid, _target in GAMES.items():
    TARGETS[_gid].append(("game_path", _target))
# Unreal games all call their exe Client-Win64-Shipping.exe, so the folder must say which
PATH_HINTS = {("wuthering", "game_path"): "wuthering"}
# Games whose exe sits deeper than the search goes: checked from every folder visited
DEEP = {("wuthering", "game_path"): os.path.join("Client", "Binaries", "Win64", "Client-Win64-Shipping.exe")}
# Where launchers install games when they aren't on a drive's top level
INSTALL_FOLDERS = ["Program Files", "Program Files (x86)", "Program Files/HoYoPlay",
                   "Program Files/HoYoPlay/games", "Program Files/Kuro Games"]

# Settings worked out from a found file, relative to its folder
DERIVED = {
    "maaend_path": {"log_dir": "debug"},
    "maa_path": {"maa_log": os.path.join("debug", "gui.log")},
    "okww_path": {"log_path": os.path.join("data", "apps", "ok-ww", "working", "logs", "ok-script.log")},
    "baas_exe": {"baas_dir": "."},
}
FOLDER_SETTINGS = {"od_dir"}  # these hold the folder the file is in, not the file

# Folders no tool lives in, and which would cost most of the time limit
SKIP = {"windows", "$recycle.bin", "system volume information", "programdata", "appdata",
        "node_modules", ".git", "__pycache__", "windowsapps", "steamapps", "_internal",
        "site-packages", "lib", "python", "cache", "logs", "temp", "tmp"}


def _matches(name, target):
    if isinstance(target, str):
        return name.lower() == target.lower()
    return bool(target.match(name))


def _wanted():
    return [(gid, key, target) for gid, items in TARGETS.items() for key, target in items]


def steam_libraries():
    """Every Steam library's steamapps/common folder, from Steam's own list of libraries."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam = winreg.QueryValueEx(key, "SteamPath")[0]
    except (ImportError, OSError):
        return []
    return libraries_in(os.path.join(steam, "steamapps", "libraryfolders.vdf"), steam)


def libraries_in(vdf, steam):
    folders = [steam]
    try:
        with open(vdf, encoding="utf-8", errors="replace") as f:
            folders += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', f.read())]
    except OSError:
        pass
    seen, out = set(), []
    for folder in folders:
        common = os.path.normpath(os.path.join(folder, "steamapps", "common"))
        if os.path.normcase(common) not in seen and os.path.isdir(common):
            seen.add(os.path.normcase(common))
            out.append(common)
    return out


def search_roots(home=None, drives=None, steam=None):
    """(folder, depth) pairs: the user's own folders a little deeper, every drive shallower,
    and the places games get installed."""
    home = Path(home or Path.home())
    roots = [(home / name, 3) for name in ("Downloads", "Desktop", "Documents", "OneDrive/Desktop")]
    roots.append((home, 1))
    if drives is None:
        drives = [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]
    roots += [(Path(d), 3) for d in drives]
    roots += [(Path(d) / sub, 3) for d in drives for sub in INSTALL_FOLDERS]
    roots += [(Path(c), 2) for c in (steam_libraries() if steam is None else steam)]
    return [(folder, depth) for folder, depth in roots if folder.is_dir()]


def _allowed(spot, path):
    hint = PATH_HINTS.get(spot)
    return hint is None or hint in path.lower()


def running_tools():
    """Paths of tool files that are running right now."""
    found = []
    for p in psutil.process_iter(["exe"]):
        exe = p.info.get("exe")
        if exe:
            found.append(exe)
    return found


def search(roots, time_limit=20, processes=None):
    """{(game id, setting): path} for every tool file found. A running tool wins; otherwise
    the most recently changed copy (a newer download of the same tool)."""
    wanted = _wanted()
    found = {}
    for exe in processes if processes is not None else running_tools():
        for gid, key, target in wanted:
            if ((gid, key) not in found and _matches(os.path.basename(exe), target)
                    and _allowed((gid, key), exe)):
                found[(gid, key)] = exe
    candidates = {}
    deadline = time.monotonic() + time_limit
    seen = set()
    queue = [(Path(folder), depth) for folder, depth in roots]
    while queue and time.monotonic() < deadline:
        folder, depth = queue.pop(0)  # breadth first: shallow places are searched first
        try:
            key = os.path.normcase(str(folder.resolve()))
            if key in seen:
                continue
            seen.add(key)
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for spot, suffix in DEEP.items():
            deep = os.path.join(str(folder), suffix)
            if spot not in found and _allowed(spot, deep) and os.path.isfile(deep):
                candidates.setdefault(spot, []).append((os.stat(deep).st_mtime, deep))
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth > 0 and entry.name.lower() not in SKIP and not entry.name.startswith("."):
                        queue.append((Path(entry.path), depth - 1))
                elif entry.is_file():
                    for gid, setting, target in wanted:
                        if ((gid, setting) not in found and _matches(entry.name, target)
                                and _allowed((gid, setting), entry.path)):
                            candidates.setdefault((gid, setting), []).append(
                                (entry.stat().st_mtime, entry.path))
            except OSError:
                continue
    for spot, paths in candidates.items():
        found.setdefault(spot, max(paths)[1])
    return found


def settings_from(found):
    """{game id: {setting: value}} from search(), including the settings that follow."""
    out = {}
    for (gid, key), path in found.items():
        values = out.setdefault(gid, {})
        folder = os.path.dirname(path)
        values[key] = folder if key in FOLDER_SETTINGS else path
        for derived, relative in DERIVED.get(key, {}).items():
            values[derived] = os.path.normpath(os.path.join(folder, relative))
    return out


def fill_missing(games_cfg, found_settings):
    """Put found values into settings that are empty or point to something that no longer
    exists, and leave everything the player set alone. Returns {game id: [changed keys]}."""
    changed = {}
    for gid, values in found_settings.items():
        game_cfg = games_cfg.get(gid)
        if game_cfg is None:
            continue
        for key, value in values.items():
            current = game_cfg.get(key)
            if not current or not os.path.exists(current):
                if current != value:
                    game_cfg[key] = value
                    changed.setdefault(gid, []).append(key)
    return changed
