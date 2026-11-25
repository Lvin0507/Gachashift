"""One button that answers "will tomorrow morning's run work?": every check Gachashift has,
plus a test message to each report channel that is turned on."""

import requests

from . import health, toolcheck
from .health import Problem


def send_test(cfg, text, post=requests.post):
    """Send `text` to each channel that is on. Returns (channels reached, problems)."""
    reached, problems = [], []
    tg, dc = cfg.get("telegram", {}), cfg.get("discord", {})
    channels = []
    if tg.get("enabled"):
        channels.append(("Telegram", f"https://api.telegram.org/bot{tg.get('bot_token', '')}/sendMessage",
                         {"chat_id": tg.get("chat_id", ""), "text": text}))
    if dc.get("enabled"):
        channels.append(("Discord", dc.get("webhook_url", ""), {"content": text}))
    for name, url, body in channels:
        try:
            r = post(url, json=body, timeout=15)
            ok = r.status_code < 300
            error = f"HTTP {r.status_code}"
        except Exception as e:
            # the exception text can hold the URL, and with it the token, so only its type
            ok, error = False, type(e).__name__
        if ok:
            reached.append(name)
        else:
            problems.append(Problem("preflight.send_failed", {"channel": name, "error": error}))
    return reached, problems


def check(cfg, text, health_check=health.check, tool_check=toolcheck.check, scheduled=None,
          missing=None, post=requests.post):
    """(problems, channels reached). Problems are ordered: setup first, then Windows, then tools.
    The helpers are parameters so tests can fake the Windows-only parts."""
    if scheduled is None or missing is None:
        from . import winutil  # Windows-only parts
        scheduled = scheduled or winutil.scheduled_time
        missing = missing or winutil.missing_items
    problems = []
    games = {gid: g for gid, g in (cfg.get("games") or {}).items() if g.get("enabled")}
    if not games:
        problems.append(Problem("preflight.no_games"))
    for gid, game_cfg in games.items():
        items = missing(gid, game_cfg)
        if items:
            problems.append(Problem("preflight.missing", {"items": items}, game=gid))
    if not scheduled():
        problems.append(Problem("preflight.no_schedule"))
    problems += health_check()
    problems += tool_check(cfg)
    reached, failed = send_test(cfg, text, post=post)
    return problems + failed, reached
