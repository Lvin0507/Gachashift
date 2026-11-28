"""Blue Archive JP (PC client) via BAAS.

The JP client must be opened from its launcher (click スタート), BAAS needs a 1280x720 window,
and BAAS exits by itself when done. Its .exe is only a launcher that starts the real BAAS
(pythonw.exe inside the BAAS folder), so we watch every process living in that folder.

BAAS writes no log file (its log only goes to its window). What it does keep is
config/<name>/event.json: each daily with the time it is next due ("next_tick"), moved past the
next reset as soon as the daily is finished. Reading that file before and after the run tells
which dailies got done, and where BAAS stopped."""

import os
import subprocess
import time

from .. import report as R
from ..system import (StallWatch, StopRequested, click_in_window, kill, kill_processes,
                      launch_and_click, main_window_of, pause, processes_in, screen_fingerprint, ts)
from ..toolcheck import baas_config_paths, read_json
from .base import Game, minutes_since

REG_KEY = r"Software\YostarJP\BlueArchive"
RESTART_GRACE = 45   # seconds BAAS may be gone while it restarts itself (an update)
WORKED_MINUTES = 3   # a runner that worked this long before being stopped did part of its list
STILL_MINUTES = 5          # the screen this long unchanged: tap where BAAS closes pop-ups
AFTER_TAP_MINUTES = 3      # still unchanged this long after the tap: BAAS is stuck
NO_PROGRESS_MINUTES = 20   # no daily finished for this long, even with the screen moving
MAX_RESTARTS = 2           # times BAAS is started again in one run after getting stuck
# where BAAS's own pop-up handler taps to close 報酬獲得 and rank-up pop-ups, as a fraction
# of the 1280x720 window (core/picture.py, deal_with_pop_ups)
TAP = (640 / 1280, 100 / 720)
GAME_EXE = "BlueArchive.exe"
# Unity stores screen settings as "<name>_h<hash>"; match on the prefix
WINDOWED = {
    "Screenmanager Fullscreen mode": 3,
    "Screenmanager Resolution Width": 1280,
    "Screenmanager Resolution Height": 720,
    "Screenmanager Resolution Window Width": 1280,
    "Screenmanager Resolution Window Height": 720,
    "Screenmanager Resolution Use Native": 0,
    "Screenmanager Window Position X": 0,
    "Screenmanager Window Position Y": 0,
}
SKIP_EVENTS = ("restart",)  # BAAS's own restart at the daily reset, not a daily


def event_paths(baas_dir):
    """event.json of each BAAS config that runs on startup (every config, when none does)."""
    configs = baas_config_paths({"baas_dir": baas_dir})
    running = [p for p, d in configs.items() if d.get("autostart") is True] or list(configs)
    return [os.path.join(os.path.dirname(p), "event.json") for p in running]


def read_events(paths):
    """{path: [daily, ...]} for each event.json that could be read."""
    found = {}
    for path in paths:
        data = read_json(path)
        if isinstance(data, list):
            found[path] = [e for e in data if isinstance(e, dict)]
    return found


def _tick(event):
    try:
        return float(event.get("next_tick") or 0)
    except (TypeError, ValueError):
        return 0.0


def _ticks(found):
    """Every daily's due time, to notice BAAS finishing one."""
    return {(path, e.get("func_name")): _tick(e) for path, events in found.items() for e in events}


def stuck_at(before, now, since):
    """The daily BAAS is working on: the first one due that it hasn't finished."""
    return next((name for name, status in daily_results(before, now, since) if status == R.FAIL), None)


def daily_results(before, after, since):
    """[(name, status)] for each daily switched on in BAAS, in the order BAAS runs them:
    ALREADY when it wasn't due, OK when BAAS finished it during the run, FAIL for the first
    due one it didn't finish (where it stopped), SKIPPED for those it never got to."""
    later = _ticks(after)
    results, stopped = [], False
    for path, events in before.items():
        for event in sorted(events, key=lambda e: e.get("priority") or 0):
            func = event.get("func_name")
            if not event.get("enabled") or func in SKIP_EVENTS:
                continue
            name = event.get("event_name") or func
            if _tick(event) > since:
                status = R.ALREADY
            elif later.get((path, func), 0) > since:
                status = R.OK
            elif not stopped:
                status, stopped = R.FAIL, True
            else:
                status = R.SKIPPED
            results.append((name, status))
    return results


def set_windowed():
    """Write the 1280x720 window BAAS needs. Full screen isn't restored: the game keeps its
    own full-screen toggle elsewhere, so the player just presses Alt+Enter."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0,
                        winreg.KEY_READ | winreg.KEY_WRITE) as key:
        i = 0
        while True:
            try:
                name = winreg.EnumValue(key, i)[0]
            except OSError:
                break
            for prefix, value in WINDOWED.items():
                if name.startswith(prefix + "_h"):
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
            i += 1


class BlueArchive(Game):
    id = "bluearchive"
    reset = (9, 4)  # 04:00 JST
    required = ("baas_dir", "launcher_path")

    def game_exes(self):
        return (GAME_EXE,)

    def launcher_exes(self):
        return (os.path.basename(self.cfg.get("launcher_path") or ""),)

    def open_launcher(self):
        launcher = self.cfg.get("launcher_path")
        if not launcher:
            return None
        return lambda: subprocess.Popen([launcher], cwd=os.path.dirname(launcher),
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def start_baas(self, baas_exe, baas_dir):
        print(f"[{ts()}] starting {baas_exe}")
        # its own console: redirecting its output crashes it on a cp932 system
        subprocess.Popen([baas_exe], cwd=baas_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)

    def screen_watch(self, minutes, screen=None):
        """A StallWatch on the screen alone (BAAS has no log), continuing from the last picture
        so a change right after a tap counts."""
        watch = StallWatch(minutes=minutes, clock=lambda: time.time(), look=lambda: screen_fingerprint())
        watch.screen = screen
        return watch

    def tap_popup(self):
        """Tap the game where BAAS itself taps to close a reward pop-up. Returns True if it did."""
        hwnd = main_window_of(GAME_EXE)
        if not hwnd:
            return False
        print(f"[{ts()}] the screen hasn't moved for {STILL_MINUTES} min; tapping where BAAS "
              f"closes pop-ups")
        return click_in_window(hwnd, *TAP)

    def run(self, start_timeout=300, timeout=3600):
        baas_dir = self.cfg["baas_dir"]
        baas_exe = self.cfg.get("baas_exe") or os.path.join(baas_dir, "BlueArchiveAutoScript.exe")
        launcher = self.cfg["launcher_path"]
        launcher_exe = os.path.basename(launcher)
        rep = self.new_report()
        try:
            set_windowed()
        except OSError as e:
            print(f"could not set window size: {e}")
        reason, saw_baas, before = "timeout", False, {}
        ran_since = gone_since = None  # BAAS's task runner first seen; BAAS last seen gone
        restarts = []      # the daily BAAS was stuck at, each time it was started again
        still_for = 0      # minutes BAAS had made no progress when it was last found stuck
        gave_up_at = None  # the daily BAAS got stuck at a second time
        start = time.time()
        try:
            ok = launch_and_click(self.open_launcher(), launcher_exe, self.cfg["start_button"],
                                  GAME_EXE, remember=self.launcher_key(),
                                  careful=self.clicks_carefully())
            if not ok:
                rep.add("baas", R.FAIL)
                rep.note("note.not_started", hint="hint.launcher")
                return rep
            start = launched = time.time()  # time BAAS itself, not the launcher
            before = read_events(event_paths(baas_dir))
            ticks = _ticks(before)
            progress_at = start  # a daily last finished (or BAAS last started)
            runner_up = False    # BAAS's task runner seen since it was last started
            self.start_baas(baas_exe, baas_dir)
            still, tapped_at = self.screen_watch(STILL_MINUTES), None
            while time.time() - start < timeout:
                # look often at first: with nothing due, BAAS can come and go in seconds
                pause(2 if time.time() - launched < 60 else 15)
                now = time.time()
                why = None
                if runner_up:
                    if still.stuck():
                        if tapped_at is None and self.tap_popup():
                            tapped_at = now
                            still = self.screen_watch(AFTER_TAP_MINUTES, still.screen)
                        else:
                            why = "stalled"
                    elif tapped_at is not None and still.last_change > tapped_at:
                        # the tap moved things on: back to the normal wait
                        tapped_at, still = None, self.screen_watch(STILL_MINUTES, still.screen)
                    if before:
                        latest = _ticks(read_events(list(before)))
                        if latest != ticks:
                            ticks, progress_at = latest, now
                        elif why is None and now - progress_at >= NO_PROGRESS_MINUTES * 60:
                            why = "no_progress"
                if why:
                    still_for = (STILL_MINUTES + AFTER_TAP_MINUTES if why == "stalled"
                                 else NO_PROGRESS_MINUTES)
                    at = stuck_at(before, read_events(list(before)), start) if before else None
                    print(f"[{ts()}] BAAS is stuck ({why}) at {at or 'an unknown daily'}")
                    if at is None or at in restarts or len(restarts) >= MAX_RESTARTS:
                        reason = "stalled"
                        gave_up_at = at if at in restarts else None
                        break
                    # what the player does by hand: stop BAAS and start it again; it skips
                    # the dailies it already finished
                    restarts.append(at)
                    kill_processes(processes_in(baas_dir))
                    time.sleep(5)
                    self.start_baas(baas_exe, baas_dir)
                    launched = progress_at = time.time()
                    runner_up, gone_since = False, None
                    still, tapped_at = self.screen_watch(STILL_MINUTES), None
                    continue
                procs = processes_in(baas_dir)
                baas_running = any((p.info.get("name") or "").lower() == "pythonw.exe" for p in procs)
                if baas_running:
                    saw_baas, runner_up, gone_since = True, True, None
                    ran_since = ran_since or time.time()
                    continue
                # BAAS's runner is gone (or never came). BAAS closes and starts again when it
                # updates itself, so only a gap that lasts counts
                if gone_since is None:
                    gone_since = time.time()
                if time.time() - gone_since < RESTART_GRACE:
                    continue
                if runner_up:
                    # BAAS itself has exited; helpers it leaves behind (e.g. adb.exe)
                    # are closed in the finally block below
                    reason = "exited"
                    break
                # BAAS was started (again, after getting stuck: then it counts as still stuck)
                # but its task runner hasn't come
                if not procs:
                    # nothing of BAAS left: it didn't stay
                    reason = "stalled" if saw_baas else "closed_early"
                    break
                if time.time() - launched > start_timeout:
                    reason = "stalled" if saw_baas else "not_started"
                    break
        except StopRequested as stop:
            # what BAAS finished before the stop, from its record; the rest wasn't run
            dailies = daily_results(before, read_events(list(before)), start) if before else []
            for name, status in dailies:
                rep.add(name, status if status in (R.OK, R.ALREADY) else R.SKIPPED)
            if not dailies:
                rep.add("baas", R.SKIPPED)
            stop.report = rep
            raise
        finally:
            self.capture([GAME_EXE, launcher_exe], baas_dir)
            kill_processes(processes_in(baas_dir))
            kill([GAME_EXE, launcher_exe])
            time.sleep(3)

        minutes = minutes_since(start)
        stalled = still_for * 60 if reason == "stalled" else 0
        worked = (time.time() - ran_since - stalled) / 60 if ran_since else 0
        print(f"[{ts()}] Blue Archive ended: {reason}, BAAS runner seen={saw_baas}, "
              f"worked about {worked:.0f} min, started again for {restarts}")
        dailies = daily_results(before, read_events(list(before)), start) if before else []
        if dailies and reason != "not_started":
            print(f"[{ts()}] BAAS dailies: " + ", ".join(f"{name}={status}" for name, status in dailies))
            # the notes say where BAAS got stuck; the generic "nothing moved" note would be
            # wrong when it went round in circles, or when starting it again got it past
            self.judge_dailies(rep, dailies, reason, minutes, restarts, gave_up_at)
            return rep
        # no record to read (event.json not found): how long BAAS worked is the best sign
        if reason == "stalled":
            self.stalled = still_for
        if reason in ("stalled", "timeout") and worked >= WORKED_MINUTES:
            rep.add("baas", R.PARTIAL)
            rep.note("note.baas_stopped_after_work", minutes=round(worked))
        elif reason == "exited" and minutes >= 3:
            rep.add("baas", R.OK)
            rep.note("note.finished", minutes=minutes)
        elif reason == "exited":
            rep.add("baas", R.WARN)
            rep.note("note.quick_exit", minutes=minutes)
        elif reason == "closed_early":
            rep.add("baas", R.WARN)
            rep.note("note.baas_closed_early", seconds=max(1, round(time.time() - start)))
        elif reason == "not_started":
            rep.add("baas", R.FAIL)
            rep.note("note.baas_not_started")
        else:
            rep.add("baas", R.WARN)
            rep.note("note.timeout", minutes=minutes)
        return rep

    @staticmethod
    def judge_dailies(rep, dailies, reason, minutes, restarts=(), gave_up_at=None):
        """Report each daily from BAAS's own record of what it finished."""
        due = [(name, status) for name, status in dailies if status != R.ALREADY]
        done = [name for name, status in due if status == R.OK]
        if due and not done and reason == "closed_early":
            # BAAS came and went without touching a daily that was due
            rep.add("baas", R.FAIL)
            rep.note("note.baas_closed_with_dailies", count=len(due))
            return
        for name, status in dailies:
            rep.add(name, status)
        stopped_at = next((name for name, status in due if status == R.FAIL), None)
        for name in restarts:
            if name != stopped_at:   # started again, and it got past this daily
                rep.note("note.baas_restarted", task=name)
        if stopped_at is None:
            if due:
                rep.note("note.finished", minutes=minutes)
        elif stopped_at == gave_up_at:
            rep.note("note.baas_stuck_twice", task=stopped_at)
        elif reason == "exited":
            rep.note("note.baas_stopped_at", task=stopped_at)
        else:
            rep.note("note.baas_stuck_at", task=stopped_at)
