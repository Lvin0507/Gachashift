"""Runs the enabled games in order, collects their reports and sends them.
Used by both the command line (python -m gachashift) and the App."""

import datetime
import json
import os
import time

import psutil

from . import report as R
from . import toolcheck
from .config import app_dir, load_config
from .games import ordered
from .i18n import game_name, t
from .report import short_name as plain
from .system import (KeepAwake, QuietMode, StopRequested, clear_stop, seconds_since_input, shutdown, ts,
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


def run_game(game_cls, game_cfg, lang, wait_reset=True, shots=None, updates=None):
    """Run one game, turning any unexpected error into a report instead of a crash.
    shots: folder for the screenshot taken before cleanup, or None for no screenshot.
    updates: the run's updater.Updates when updates are handled; an update the game's
    launcher started is attached to the report as rep.update."""
    game = game_cls(game_cfg)
    game.shot_dir = shots
    game.updater = updates
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
            rep.failure_shots = list(game.failure_shots)
        if game.stalled:
            rep.note("note.stalled", minutes=game.stalled)
        rep.update = game.update
        return explain(rep, game_cfg, game)
    except StopRequested:
        raise  # not an error: the whole run stops
    except Exception as e:
        print(f"[{ts()}] {game.id} failed: {e}")
        rep.note("note.error", error=f"{type(e).__name__}: {e}")
        rep.screenshot = game.shot or ""
        rep.failure_shots = list(game.failure_shots)
        return explain(rep, game_cfg, game)


def explain(rep, game_cfg, game=None):
    """When a game didn't go well, add what would explain it: a launcher left open without
    its game (usually a client update), and the tool's settings that differ from ours."""
    if R.outcome(rep) != "ok":
        if game is not None and game.launcher_left and not getattr(rep, "update", None):
            rep.note("note.maybe_update")
        for key in toolcheck.check_game(rep.game, game_cfg):
            rep.note(key)
    return rep


def remove_file(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


# Notes that say the run itself ended badly: the screen at the end shows why
END_SHOT_NOTES = ("note.error", "note.stalled", "note.timeout", "note.not_started", "note.no_records",
                  "note.no_done_marker", "note.maybe_update", "note.update_failed",
                  "note.baas_not_started", "note.baas_stopped_after_work", "note.locked")


def end_shot_wanted(rep):
    """The picture taken at the end is worth sending when the game ended badly: nothing got
    done, the run went wrong (a timeout, a crash, a client update), or the last task failed.
    A task that failed earlier, with later ones done, says nothing about the end: the screen
    has long moved on (tools that report failures as they happen get their own pictures)."""
    if R.outcome(rep) == "fail":
        return True
    if any(key in END_SHOT_NOTES for key, _ in rep.notes):
        return True
    ran = [task for task in rep.tasks if task.status not in (R.SKIPPED, R.NOTHING)]
    return bool(ran) and ran[-1].status == R.FAIL


def discard_pictures(rep):
    remove_file(rep.screenshot)
    rep.screenshot = ""
    for _, path in rep.failure_shots:
        remove_file(path)
    rep.failure_shots = []


def screenshots_to_send(reports, stopped, lang):
    """(caption, path) for each picture worth sending: one per failed task where the tool says
    so while it runs, then the screen at the end when the game ended badly. The rest, and every
    picture of a run the user stopped, are deleted."""
    photos = []
    for rep in reports:
        game = R.short_name(rep.game, lang)
        if stopped or R.outcome(rep) == "ok":
            discard_pictures(rep)
            continue
        for key, path in rep.failure_shots:
            photos.append((t(lang, "photo.task_failed", game=game, task=rep.label(key, lang)), path))
        if rep.screenshot and end_shot_wanted(rep):
            photos.append((t(lang, "photo.caption", game=game), rep.screenshot))
        elif rep.screenshot:
            remove_file(rep.screenshot)
            rep.screenshot = ""
    return photos


def prune_screenshots(keep_days=SCREENSHOT_DAYS):
    folder = screenshot_folder()
    cutoff = time.time() - keep_days * 86400
    for old in folder.glob("*.jpg") if folder.exists() else []:
        if old.stat().st_mtime < cutoff:
            remove_file(old)


# The tool stopped partway through its own list: a second run picks up what is left (BAAS
# skips what it already did). 27 Nov: BAAS got stuck after 4 min, and the second run did 11
# more minutes of dailies.
RETRY_NOTES = ("note.baas_stopped_after_work",)


def stuck_partway(rep):
    return any(key in RETRY_NOTES for key, _ in rep.notes)


def needs_retry(rep):
    """True when nothing in the game got done: the game didn't start, the tool left no records,
    or its only task failed. Those are usually one-off (a client update, a slow first launch)
    and pass on a second try. A run where some tasks worked and some failed isn't repeated:
    the failures there are usually the same every time."""
    if stuck_partway(rep):
        return True
    if not R.nothing_done(rep):
        return False
    # a setting that was never filled in won't fix itself on a second try
    return not any("missing settings" in str(params.get("error", "")) for _, params in rep.notes)


def games_to_run(cfg, only, lang, log):
    """The game classes this run will play, in order, logging why the others are skipped."""
    todo = []
    for game_cls in ordered(cfg):
        gid = game_cls.id
        game_cfg = cfg["games"].get(gid, {})
        if only:
            if gid == only:
                todo.append(game_cls)
        elif not game_cfg.get("enabled"):
            log(t(lang, "log.skip_off", game=game_name(gid, lang)))
        elif not due_today(game_cfg):
            log(t(lang, "log.skip_day", game=game_name(gid, lang)))
        else:
            todo.append(game_cls)
    return todo


def make_updates(opts, log):
    if not opts.get("update_games"):
        return None
    from .updater import Updates
    return Updates(log=lambda text: log(f"[{ts()}] {text}"))


def run_games(cfg, only, lang, opts, log, dim=False, shots=None, status=None, updates=None):
    """Run every game that is enabled and due today (or just `only`) and return their reports.
    In a full run, a game where nothing got done is tried once more after all the others.
    With updates handled ("Update games first"), a game whose client is updating is played
    after the others, once its update is done.
    status: called with a short line about what is running now (the tray icon)."""
    status = status or (lambda text: None)
    reports, retry, later = [], [], []
    updates = updates if updates is not None else make_updates(opts, log)
    with QuietMode(mute=opts.get("mute", True), dim=dim,
                   dim_level=opts.get("dim_level", 30) / 100):
        todo = games_to_run(cfg, only, lang, log)
        try:
            if updates:
                status(t(lang, "tray.checking_updates"))
                updates.before_run([g(cfg["games"].get(g.id, {})) for g in todo])
            for number, game_cls in enumerate(todo, 1):
                gid = game_cls.id
                game_cfg = cfg["games"].get(gid, {})
                if updates and updates.blocking(game_cls(game_cfg)):
                    log(f"[{ts()}] " + t(lang, "log.after_update", game=game_name(gid, lang)))
                    placeholder = R.GameReport(gid)  # filled in once it has run
                    placeholder.waiting = True
                    reports.append(placeholder)
                    later.append((len(reports) - 1, game_cls, game_cfg, 0))
                    continue
                status(t(lang, "tray.running", game=plain(gid, lang), n=number, total=len(todo)))
                # a single-game test run shouldn't sit waiting for a reset
                try:
                    reports.append(run_game(game_cls, game_cfg, lang, wait_reset=not only,
                                            shots=shots, updates=updates))
                except StopRequested as stop:
                    # the game closed its own tool and game on the way out and, where it could,
                    # attached what it finished before the stop; keep that and earlier reports
                    if getattr(stop, "report", None):
                        reports.append(stop.report)
                    reports.append(stopped_report())
                    return played(reports), True
                failed = updates.failed.pop(gid, None) if updates else None
                if failed:
                    reports[-1].notes.insert(0, ("note.update_failed", {"reason": failed}))
                if getattr(reports[-1], "update", None):
                    later.append((len(reports) - 1, game_cls, game_cfg, 1))
                # a test run of one game has someone watching it; they can just run it again
                elif (not only and game_cfg.get("retry", True) and needs_retry(reports[-1])
                        and reports[-1].seconds < RETRY_MAX_MINUTES * 60):
                    retry.append((len(reports) - 1, game_cls, game_cfg))

            while later:
                index, game_cls, game_cfg, attempts = later.pop(0)
                rep = after_update(game_cls, game_cfg, lang, updates, shots, status, log)
                if getattr(rep, "update", None) and attempts < 2:
                    # the launcher had another update once Steam's was done: wait for that too
                    later.append((index, game_cls, game_cfg, attempts + 1))
                discard_pictures(reports[index])
                reports[index] = rep
        except StopRequested as stop:
            if getattr(stop, "report", None):
                reports.append(stop.report)
            reports.append(stopped_report())
            return played(reports), True
        finally:
            if updates:
                updates.finish_all()

        for index, game_cls, game_cfg in retry:
            # "nothing got done" or "got stuck partway": the report says which
            why = "note.retried_rest" if stuck_partway(reports[index]) else "note.retried"
            log(f"[{ts()}] " + t(lang, "log.retry_rest" if why == "note.retried_rest" else "log.retry",
                                 game=game_name(game_cls.id, lang)))
            status(t(lang, "tray.retrying", game=plain(game_cls.id, lang)))
            try:
                rep = run_game(game_cls, game_cfg, lang, wait_reset=False, shots=shots)
            except StopRequested as stop:
                if getattr(stop, "report", None):
                    stop.report.note(why)
                    reports[index] = stop.report
                reports.append(stopped_report())
                return reports, True
            # the second attempt is what the game is in now, so it replaces the first
            rep.note(why)
            discard_pictures(reports[index])
            reports[index] = rep
    return reports, False


def played(reports):
    """The reports without the places kept for games that never got to run."""
    return [r for r in reports if not getattr(r, "waiting", False)]


def after_update(game_cls, game_cfg, lang, updates, shots, status, log):
    """Wait for the game's update (or the one in its launcher), then run the game."""
    game = game_cls(game_cfg)
    own = updates.take(game.id)
    other = updates.blocking(game)
    note = None
    for update in (u for u in (own, other) if u):
        status(t(lang, "tray.waiting_update", game=plain(game.id, lang)))
        log(f"[{ts()}] " + t(lang, "log.waiting_update", game=game_name(game.id, lang)))
        result = update.wait()
        if update is own:
            source = "hint.update_steam" if update.kind == "steam" else "hint.update_launcher"
            note = (("note.updated", {"source": source, "minutes": update.minutes()})
                    if result == "done" else ("note.update_failed", {"reason": result}))
        # close what the update left open (the launcher, or the game Steam started after
        # updating), so the game starts the usual way
        from .system import kill
        kill(list(game.launcher_exes()) + list(game.game_exes()))
    status(t(lang, "tray.running_after_update", game=plain(game.id, lang)))
    rep = run_game(game_cls, game_cfg, lang, wait_reset=False, shots=shots, updates=updates)
    if note:
        rep.notes.insert(0, note)
    failed = updates.failed.pop(game.id, None)
    if failed:
        rep.notes.insert(0, ("note.update_failed", {"reason": failed}))
    return rep


def stopped_report():
    rep = R.GameReport("system")
    rep.note("note.stopped")
    return rep


def run_all(cfg=None, only=None, allow_shutdown=True, send=True, ask_first=False, log=print,
            tray=False, dim=False):
    """Run the games, then send the report and (optionally) shut down.
    ask_first: for scheduled runs, ask before starting if someone is using the PC.
    tray: show a tray icon with the game that is running and a way to stop.
    dim: darken the screen even though this isn't the scheduled run (Run page's switch)."""
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
    icon = None
    if tray:
        from .tray import RunTray
        icon = RunTray(lang)
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
            with KeepAwake():
                reports, stopped = run_games(cfg, only, lang, opts, log, shots=shots,
                                             dim=dim or (ask_first and opts.get("dim_screen", False)),
                                             status=icon.status if icon else None)
    except StopRequested:  # stopped while waiting for the lock screen to clear
        stopped = True
        reports.append(stopped_report())
    finally:
        if icon:
            icon.close()
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
