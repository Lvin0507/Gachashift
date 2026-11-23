"""Pack what's needed to work out a problem into one zip, with private details removed, so
a player can send it to whoever helps them instead of hunting for log files.

Inside: the last few days of Gachashift's run logs, the recent screenshots, the end of each
tool's own log, the settings (without the Telegram token, chat ID or Discord webhook), and
a summary of the PC and the paths. Tokens, webhooks, game UIDs, the Windows user folder,
account SIDs and e-mail addresses are removed from every text file."""

import datetime
import json
import os
import platform
import re
import sys
import time
import zipfile
from pathlib import Path

from . import __version__
from .config import app_dir
from .games import ordered

TELEGRAM_TOKEN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
DISCORD_WEBHOOK = re.compile(r"https://(?:[\w-]+\.)?discord(?:app)?\.com/api/webhooks/\S+", re.I)
SID = re.compile(r"S-1-5-21(?:-\d+)+")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
UID = re.compile(r"(?:UID|识别值)[^0-9\r\n]{0,12}(\d{6,12})", re.I)
REMOVED = "(removed)"


def redactor(cfg, home=None):
    """A function that removes private details from text, knowing this player's secrets."""
    secrets = [cfg.get("telegram", {}).get("bot_token", ""), cfg.get("discord", {}).get("webhook_url", "")]
    chat = str(cfg.get("telegram", {}).get("chat_id", ""))
    if len(chat) >= 5:  # short values would match ordinary numbers
        secrets.append(chat)
    secrets = [s for s in secrets if s]
    home = str(home or Path.home())
    homes = {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}

    def redact(text):
        for secret in secrets:
            text = text.replace(secret, REMOVED)
        text = TELEGRAM_TOKEN.sub(REMOVED, text)
        text = DISCORD_WEBHOOK.sub(REMOVED, text)
        text = SID.sub(REMOVED, text)
        text = EMAIL.sub(REMOVED, text)
        for uid in set(UID.findall(text)):  # the number may appear again elsewhere
            text = text.replace(uid, REMOVED)
        for h in homes:
            text = re.sub(re.escape(h), "%USERPROFILE%", text, flags=re.I)
        return text

    return redact


def safe_settings(cfg):
    """The settings without anything that would let someone post as the player."""
    out = json.loads(json.dumps(cfg))
    tg = out.get("telegram", {})
    for key in ("bot_token", "chat_id"):
        if tg.get(key):
            tg[key] = REMOVED
    if out.get("discord", {}).get("webhook_url"):
        out["discord"]["webhook_url"] = REMOVED
    return out


def tool_logs(cfg, today=None):
    """(name in the zip, path) of each enabled game's own log."""
    today = today or datetime.date.today()
    games = cfg.get("games", {})
    found = []
    for game_cls in ordered(cfg):
        gid, g = game_cls.id, games.get(game_cls.id, {})
        if not g.get("enabled"):
            continue
        if gid == "endfield" and g.get("log_dir"):
            found.append((f"tools/{gid}-go-service.log", os.path.join(g["log_dir"], "go-service.log")))
        elif gid == "arknights" and g.get("maa_log"):
            found.append((f"tools/{gid}-gui.log", g["maa_log"]))
        elif gid == "wuthering" and g.get("log_path"):
            found.append((f"tools/{gid}-ok-script.log", g["log_path"]))
        elif gid == "zzz" and g.get("od_dir"):
            found.append((f"tools/{gid}-log.txt", os.path.join(g["od_dir"], ".log", "log.txt")))
        elif gid == "genshin" and g.get("bgi_path"):
            folder = os.path.join(os.path.dirname(g["bgi_path"]), "log")
            for day in (today - datetime.timedelta(days=1), today):
                found.append((f"tools/{gid}-{day:%Y%m%d}.log",
                              os.path.join(folder, f"better-genshin-impact{day:%Y%m%d}.log")))
    return [(name, path) for name, path in found if os.path.isfile(path)]


def tail(path, size):
    """The last `size` bytes of a file, as text."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - size))
        return f.read().decode("utf-8", errors="replace")


def summary(cfg):
    lines = [f"Gachashift {__version__} ({'exe' if getattr(sys, 'frozen', False) else 'source'})",
             f"Windows: {platform.platform()}", f"Python: {platform.python_version()}",
             f"Made: {datetime.datetime.now():%Y-%m-%d %H:%M}", "", "Games, in run order:"]
    for game_cls in ordered(cfg):
        g = cfg.get("games", {}).get(game_cls.id, {})
        lines.append(f"- {game_cls.id}: {'on' if g.get('enabled') else 'off'}, days {g.get('days')}")
        for key, value in g.items():
            if isinstance(value, str) and (":\\" in value or value.startswith(("/", "\\\\"))):
                lines.append(f"    {key}: {value} ({'found' if os.path.exists(value) else 'NOT FOUND'})")
    last = app_dir() / "last_run.json"
    if last.exists():
        lines += ["", "Last results:", last.read_text(encoding="utf-8", errors="replace")]
    return "\n".join(lines) + "\n"


def build(cfg, dest=None, days=3, tool_bytes=2_000_000, home=None):
    """Write the zip and return its path. dest: the folder for it (the Desktop by default)."""
    redact = redactor(cfg, home)
    logs = app_dir() / "logs"
    if dest is None:
        desktop = Path(home or Path.home()) / "Desktop"
        dest = desktop if desktop.is_dir() else logs
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"gachashift-report-{datetime.datetime.now():%Y%m%d-%H%M}.zip"
    cutoff = time.time() - days * 86400

    def recent(pattern):
        return sorted(p for p in logs.glob(pattern) if p.stat().st_mtime >= cutoff) if logs.exists() else []

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("about.txt", redact(summary(cfg)))
        z.writestr("settings.json", redact(json.dumps(safe_settings(cfg), ensure_ascii=False, indent=2)))
        for log in recent("gachashift_*.log") + recent("update.log") + recent("go-service_*.log")[-1:]:
            z.writestr(f"logs/{log.name}", redact(log.read_text(encoding="utf-8", errors="replace")))
        for shot in recent("screens/*.jpg"):
            z.write(shot, f"screens/{shot.name}")
        for name, tool_log in tool_logs(cfg):
            try:
                z.writestr(name, redact(tail(tool_log, tool_bytes)))
            except OSError:
                pass
    return path
