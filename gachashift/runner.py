"""Runs the enabled games in order, collects their reports and sends them.
Used by both the command line (python -m gachashift) and the App."""

import datetime
import json
import os
import time

import psutil

from . import report as R
from .config import app_dir, load_config
from .games import GAMES
from .i18n import game_name, t
from .system import (QuietMode, StopRequested, clear_stop, seconds_since_input, shutdown, ts,
                     wait_for_reset, wait_for_unlock)

ACTIVE_SECONDS = 120  # someone used the PC this recently: ask before taking over
SCREENSHOT_DAYS = 14  # failure screenshots are kept this long under logs/screens

# A game whose first attempt took longer than this isn't retried: it most likely hung until
# its timeout, and a second hang would hold up the morning for as long again
RETRY_MAX_MINUTES = 40


def running_file():
    """Present while a run is in progress, so the App can show a Stop button."""
    return app_dir() / "running.json"


def last_results_file():
    """Each game's most recent result, for the App's Home page."""
    return app_dir() / "last_run.json"


def load_last_results():
    try:
        return json.loads(last_results_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_last_results(reports):
    """Remember how each game that ran just now went; games that didn't run keep their
    earlier result."""
    results = load_last_results()
    now = datetime.datetime.now().isoformat(timespec="minutes")
    for rep in reports:
        if rep.game != "system":
            results[rep.game] = {"time": now, "outcome": R.outcome(rep),
                                 "failed": sum(task.status == R.FAIL for task in rep.tasks)}
    try:
        last_results_file().write_text(json.dumps(results, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"Could not save the results for Home: {e}")


def unfinished_run():
    """When the last run was cut off (power loss, crash, the process killed), its running.json
    is still there and its process is gone. Returns when it started ("11-20 07:00"), or None."""
    path = running_file()
    try:
        info = json.loads(path.read_text())
        started = datetime.datetime.fromtimestamp(path.stat().st_mtime)
    except (OSError, ValueError):
        return None
    if psutil.pid_exists(info.get("pid", -1)):
        return None  # still running (the App checks this before starting another run)
    return started.strftime("%m-%d %H:%M")


def due_today(game_cfg):
    return game_cfg.get("enabled") and datetime.datetime.today().weekday() in game_cfg.get("days", [])


def screenshot_folder():
    return app_dir() / "logs" / "screens"


def run_game(game_cls, game_cfg, lang, wait_reset=True, shots=None):
    """Run one game, turning any unexpected error into a report instead of a crash.
    shots: folder for the screenshot taken before cleanup, or None for no screenshot."""
    game = game_cls(game_cfg)
    game.shot_dir = shots
    rep = R.GameReport(game.id)
    missing = game.missing_settings()
    if missing:
        rep.note("note.error", error="missing settings: " + ", ".join(missing))
        return rep
    try:
        if wait_reset and game.reset and game_cfg.get("wait_for_reset", True):
            offset, hour = game.reset
            wait_for_reset(offset, hour, on_wait=lambda m: print(
                f"[{ts()}] " + t(lang, "log.wait_reset", game=game_name(game.id, lang), minutes=m)))
        started = time.time()
        try:
            rep = game.run()
        finally:
            rep.seconds = time.time() - started
            rep.screenshot = game.shot or ""
        return rep
    except StopRequested:
        raise  # not an error: the whole run stops
    except Exception as e:
        print(f"[{ts()}] {game.id} failed: {e}")
        rep.note("note.error", error=f"{type(e).__name__}: {e}")
        rep.screenshot = game.shot or ""
        return rep


def remove_file(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def screenshots_to_send(reports, stopped, lang):
    """(caption, path) for each game that didn't go well. Pictures of games that went fine,
    and every picture of a run the user stopped, are deleted."""
    photos = []
    for rep in reports:
        if not rep.screenshot:
            continue
        if stopped or R.outcome(rep) == "ok":
            remove_file(rep.screenshot)
            rep.screenshot = ""
        else:
            photos.append((t(lang, "photo.caption", game=R.short_name(rep.game, lang)), rep.screenshot))
    return photos


def prune_screenshots(keep_days=SCREENSHOT_DAYS):
    folder = screenshot_folder()
    cutoff = time.time() - keep_days * 86400
    for old in folder.glob("*.jpg") if folder.exists() else []:
        if old.stat().st_mtime < cutoff:
            remove_file(old)


def needs_retry(rep):
    """True when nothing in the game got done: the game didn't start, the tool left no records,
    or its only task failed. Those are usually one-off (a client update, a slow first launch)
    and pass on a second try. A run where some tasks worked and some failed isn't repeated:
    the failures there are usually the same every time."""
    if not R.nothing_done(rep):
        return False
    # a setting that was never filled in won't fix itself on a second try
    return not any("missing settings" in str(params.get("error", "")) for _, params in rep.notes)


def run_games(cfg, only, lang, opts, log, dim=False, shots=None):
    """Run every game that is enabled and due today (or just `only`) and return their reports.
    In a full run, a game where nothing got done is tried once more after all the others."""
    reports, retry = [], []
    with QuietMode(mute=opts.get("mute", True), dim=dim,
                   dim_level=opts.get("dim_level", 30) / 100):
        for game_cls in GAMES:
            gid = game_cls.id
            game_cfg = cfg["games"].get(gid, {})
            if only:
                if gid != only:
                    continue
            elif not game_cfg.get("enabled"):
                log(t(lang, "log.skip_off", game=game_name(gid, lang)))
                continue
            elif not due_today(game_cfg):
                log(t(lang, "log.skip_day", game=game_name(gid, lang)))
                continue
            # a single-game test run shouldn't sit waiting for a reset
            try:
                reports.append(run_game(game_cls, game_cfg, lang, wait_reset=not only, shots=shots))
            except StopRequested as stop:
                # the game closed its own tool and game on the way out and, where it could,
                # attached what it finished before the stop; keep that and earlier reports
                if getattr(stop, "report", None):
                    reports.append(stop.report)
                reports.append(stopped_report())
                return reports, True
            # a test run of one game has someone watching it; they can just run it again
            if (not only and game_cfg.get("retry", True) and needs_retry(reports[-1])
                    and reports[-1].seconds < RETRY_MAX_MINUTES * 60):
                retry.append((len(reports) - 1, game_cls, game_cfg))

        for index, game_cls, game_cfg in retry:
            log(f"[{ts()}] " + t(lang, "log.retry", game=game_name(game_cls.id, lang)))
            try:
                rep = run_game(game_cls, game_cfg, lang, wait_reset=False, shots=shots)
            except StopRequested as stop:
                if getattr(stop, "report", None):
                    stop.report.note("note.retried")
                    reports[index] = stop.report
                reports.append(stopped_report())
                return reports, True
            # the second attempt is what the game is in now, so it replaces the first
            rep.note("note.retried")
            remove_file(reports[index].screenshot)
            reports[index] = rep
    return reports, False


def stopped_report():
    rep = R.GameReport("system")
    rep.note("note.stopped")
    return rep


def run_all(cfg=None, only=None, allow_shutdown=True, send=True, ask_first=False, log=print):
    """Run the games, then send the report and (optionally) shut down.
    ask_first: for scheduled runs, ask before starting if someone is using the PC."""
    cfg = cfg or load_config()
    lang = cfg.get("report_language", "en")
    opts = cfg["options"]
    clear_stop()  # an old request must not stop this run

    if ask_first and seconds_since_input() < ACTIVE_SECONDS:
        from .prompt import ask_before_start
        if not ask_before_start(lang):
            log(f"[{ts()}] " + t(lang, "log.skipped_by_user"))
            return []

    reports, stopped, notices = [], False, []
    cut_off = None if only else unfinished_run()
    if cut_off:
        rep = R.GameReport("system")
        rep.note("note.previous_unfinished", started=cut_off)
        notices.append(rep)
    running_file().write_text(json.dumps({"pid": os.getpid(), "started": ts(), "only": only}))
    try:
        # On the lock screen no tool can see or click anything, so report it instead of hanging
        if not only and not wait_for_unlock():
            rep = R.GameReport("system")
            rep.note("note.locked")
            reports.append(rep)
        else:
            # only the scheduled run darkens the screen; someone is watching any other run
            # a test run has someone watching, so it takes no pictures
            shots = None if only or not opts.get("screenshots", True) else str(screenshot_folder())
            reports, stopped = run_games(cfg, only, lang, opts, log, shots=shots,
                                         dim=ask_first and opts.get("dim_screen", False))
    except StopRequested:  # stopped while waiting for the lock screen to clear
        stopped = True
        reports.append(stopped_report())
    finally:
        try:
            running_file().unlink()
        except FileNotFoundError:
            pass
        clear_stop()

    reports = notices + reports  # a note about the last run goes above this run's games
    save_last_results(reports)
    text = R.render_all(reports, lang)
    log("\n" + text + "\n")
    tg = cfg["telegram"]
    if send and tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id") and reports:
        R.send_telegram(tg["bot_token"], tg["chat_id"], reports, lang)
    dc = cfg.get("discord", {})
    if send and dc.get("enabled") and dc.get("webhook_url") and reports:
        R.send_discord(dc["webhook_url"], reports, lang)
    photos = screenshots_to_send(reports, stopped, lang)
    if send and photos:
        R.send_photos(cfg, photos)
    prune_screenshots()
    if allow_shutdown and opts.get("shutdown", True) and not stopped:
        shutdown()
    return reports
