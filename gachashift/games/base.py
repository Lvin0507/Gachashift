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
