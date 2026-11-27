"""Common shape of a game module."""

import datetime
import os
import time

from ..report import GameReport
from ..system import StallWatch, capture_screen, process_running, processes_in, stop_requested, ts


MAX_FAILURE_SHOTS = 3  # pictures of failed tasks per game, besides the one at the end
HEAD_BYTES = 256


class LiveLog:
    """Follows a tool's log while the tool runs, one complete line at a time.

    It keeps its own place in the file and its own copy of the file's first bytes, so a tool
    that starts a new log file (OneDragon does, once a day) is read again from the top."""

    def __init__(self, path, offset=0, encoding="utf-8"):
        self.path, self.offset, self.encoding = path, offset, encoding
        self.head = self._head() if offset else b""

    def _head(self):
        try:
            with open(self.path, "rb") as f:
                return f.read(HEAD_BYTES)
        except OSError:
            return b""

    def poll(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return
        head = self._head()
        if size < self.offset or (self.head and head[:len(self.head)] != self.head):
            self.offset = 0  # a new file
        self.head = head if len(head) > len(self.head) or self.offset == 0 else self.head
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                data = f.read()
        except OSError:
            return
        end = data.rfind(b"\n")
        if end < 0:
            return
        self.offset += end + 1
        for raw in data[:end + 1].decode(self.encoding, errors="ignore").splitlines():
            self.line(raw.strip())

    def line(self, raw):
        """One line of the log, without its line break."""


class FailureShots(LiveLog):
    """Takes a picture of the screen when the tool says a task failed, while it runs.

    Subclasses read their tool's lines and call begin() when a task starts, error() when it
    hits an error it may still recover from, failed() and succeeded() when it ends. An error
    takes a picture at once (the screen where the task got stuck); it is kept if the task
    then fails and deleted if it recovers. snap(key) takes a picture and returns its path,
    remove(path) deletes one."""

    def __init__(self, path, snap, remove, offset=0, encoding="utf-8"):
        super().__init__(path, offset, encoding)
        self.snap, self.remove = snap, remove
        self.current = None      # (task id, key) of the task running now
        self.pending = {}        # task id -> (key, path) taken at an error, not yet confirmed
        self.kept = []           # (key, path) of the tasks that failed
        self.done = set()        # task ids that already have a kept picture

    def begin(self, task_id, key):
        self.finish_current()
        self.current = (task_id, key)

    def error(self):
        if not self.current:
            return
        task_id, key = self.current
        if task_id not in self.pending and task_id not in self.done:
            path = self.snap(key)
            if path:
                self.pending[task_id] = (key, path)

    def failed(self, task_id, key):
        if task_id in self.done:
            return
        shot = self.pending.pop(task_id, None)
        if shot is None:
            path = self.snap(key)
            shot = (key, path) if path else None
        if shot:
            self.kept.append(shot)
            self.done.add(task_id)

    def succeeded(self, task_id):
        shot = self.pending.pop(task_id, None)
        if shot:
            self.remove(shot[1])

    def finish_current(self):
        """A task with an error that ended without failing: drop its picture."""
        if self.current:
            self.succeeded(self.current[0])

    def close(self):
        self.poll()
        self.finish_current()
        for _, path in self.pending.values():
            self.remove(path)
        self.pending = {}
        return self.kept


def remove_file(path):
    try:
        os.remove(path)
    except OSError:
        pass


class Game:
    id = ""
    # (utc offset, reset hour) of the server's daily reset, or None
    reset = None
    # config keys that must be filled in before the game can run
    required = ()

    def __init__(self, cfg):
        self.cfg = cfg
        self.shot_dir = None  # set by the runner when failure screenshots are on
        self.shot = None      # the screenshot taken before cleanup, if any
        self.stalled = 0      # minutes without progress, if the game was ended for that
        self.launcher_left = False  # its launcher was open but the game wasn't, at cleanup
        self.updater = None   # updater.Updates when "Update games first" is on
        self.update = None    # an update this run started for the game, still downloading
        self.failure_shots = []  # (task key, path) taken while the tool ran, as a task failed

    def game_exes(self):
        """The game's own process names."""
        return ()

    def launcher_exes(self):
        """Launchers that open the game. One still open without the game usually means it is
        showing an update instead of a start button."""
        return ()

    def launcher_running(self):
        return any(process_running(n) for n in self.launcher_exes() if n)

    def check_launcher(self):
        if self.launcher_running():
            self.launcher_left = not any(process_running(n) for n in self.game_exes() if n)
        if self.launcher_left and self.updater and not stop_requested():
            # the launcher is still showing this game's page: start the update right here
            # (not after a stop: the player wants everything closed, not an update clicked)
            try:
                self.update = self.updater.start_in_run(self)
            except Exception as e:  # cleanup must go on (a stop request is seen again later)
                print(f"[{ts()}] {self.id}: could not start the update: {type(e).__name__}: {e}")

    # --- updates (see updater.py) ---

    def launcher_key(self):
        """Name the learned start button is kept under."""
        exes = [n for n in self.launcher_exes() if n]
        return f"{self.id}:{exes[0].lower()}" if exes else ""

    def launcher_group(self):
        """Games whose launcher is the same program wait for each other's updates."""
        exes = [n for n in self.launcher_exes() if n]
        return exes[0].lower() if exes else ""

    def launcher_screen(self):
        from ..updater import WindowsScreen
        exes = [n for n in self.launcher_exes() if n]
        return WindowsScreen(exe=exes[0] if exes else None, game_exes=self.game_exes())

    def steam_app(self):
        """(app id or None, game exe path or "") when the game comes from Steam, else None."""
        return None

    def open_launcher(self):
        """Opens the game's launcher without starting the game, when Gachashift can (for the
        check before the run); None otherwise."""
        return None

    def clicks_carefully(self):
        """launch_and_click's careful mode: on when updates are handled."""
        return bool(self.updater)

    def watch(self, log=None):
        """A StallWatch for this game's wait loop."""
        return StallWatch(log)

    def stuck(self, watch):
        """True (and remembered for the report) once nothing has moved for watch.minutes."""
        if watch.stuck():
            self.stalled = watch.minutes
            print(f"[{ts()}] {self.id}: no progress for {watch.minutes} min; ending it")
            return True
        return False

    def capture(self, exe_names=(), folder=None):
        """Called first in each game's cleanup, before anything is closed: if the game, its
        launcher or its tool is still open, keep a picture of the screen. The runner sends it
        only if the game didn't go well, and deletes it otherwise. When everything was already
        closed (the tool shut down by itself), the picture would only show the desktop."""
        self.check_launcher()
        if not self.shot_dir:
            return
        if not (any(process_running(n) for n in exe_names if n) or (folder and processes_in(folder))):
            return
        name = f"{datetime.datetime.now():%Y-%m-%d_%H%M%S}_{self.id}.jpg"
        self.shot = capture_screen(os.path.join(self.shot_dir, name))

    def snap(self, key):
        """A picture of the screen right now, for a task that just failed; its path or None.
        Only when screenshots are on, and at most MAX_FAILURE_SHOTS per game."""
        if not self.shot_dir or len(self.failure_shots) >= MAX_FAILURE_SHOTS:
            return None
        safe = "".join(c if c.isalnum() else "-" for c in key)[:40]
        name = f"{datetime.datetime.now():%Y-%m-%d_%H%M%S}_{self.id}_{safe}.jpg"
        return capture_screen(os.path.join(self.shot_dir, name))

    def missing_settings(self):
        return [key for key in self.required if not self.cfg.get(key)]

    def new_report(self):
        return GameReport(self.id)

    def run(self):
        raise NotImplementedError


def minutes_since(start):
    return round((time.time() - start) / 60)
