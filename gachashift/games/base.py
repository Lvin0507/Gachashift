"""Common shape of a game module."""

import datetime
import os
import time

from ..report import GameReport
from ..system import StallWatch, capture_screen, process_running, processes_in, ts


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
        if self.launcher_left and self.updater:
            # the launcher is still showing this game's page: start the update right here
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

    def missing_settings(self):
        return [key for key in self.required if not self.cfg.get(key)]

    def new_report(self):
        return GameReport(self.id)

    def run(self):
        raise NotImplementedError


def minutes_since(start):
    return round((time.time() - start) / 60)
