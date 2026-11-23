"""Ending a game early when nothing moves, and never when the screen can't be seen."""

import os
import tempfile
import unittest

from gachashift.games.base import Game
from gachashift.system import StallWatch, looks_different

STILL, MOVED, BLACK = bytes([100] * 16), bytes([140] * 16), None


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class StallWatchTest(unittest.TestCase):
    def watch(self, screens, log=None):
        clock, frames = Clock(), iter(screens)
        w = StallWatch(log, minutes=15, clock=clock, look=lambda: next(frames))
        return w, clock

    def run_minutes(self, watch, clock, minutes, step=1, grow=None):
        """Check once a minute; returns the minute it first reported stuck, or None."""
        for m in range(1, minutes + 1, step):
            clock.now = m * 60
            if grow:
                grow(m)
            if watch.stuck():
                return m
        return None

    def test_still_screen_no_log(self):
        w, clock = self.watch([STILL] * 30)
        self.assertEqual(self.run_minutes(w, clock, 30), 16)  # first look at 1, 15 min later

    def test_moving_screen_never_stuck(self):
        w, clock = self.watch([STILL, MOVED] * 15)
        self.assertIsNone(self.run_minutes(w, clock, 30))

    def test_black_screen_never_stuck(self):
        # display off or locked: the picture is unknown, so a quiet tool isn't judged by it
        w, clock = self.watch([BLACK] * 30)
        self.assertIsNone(self.run_minutes(w, clock, 30))

    def test_growing_log_keeps_it_alive(self):
        with tempfile.TemporaryDirectory() as folder:
            log = os.path.join(folder, "tool.log")
            open(log, "w").close()
            w, clock = self.watch([STILL] * 60, log=log)

            def grow(minute):
                if minute < 25:
                    with open(log, "a") as f:
                        f.write("still working\n")

            # the screen is still the whole time, but the log grows until minute 24
            self.assertEqual(self.run_minutes(w, clock, 45, grow=grow), 39)

    def test_flicker_is_not_movement(self):
        self.assertFalse(looks_different(STILL, bytes([101] * 16)))
        self.assertTrue(looks_different(STILL, MOVED))


class FingerprintTest(unittest.TestCase):
    def image(self, colour, square=None):
        from PySide6.QtGui import QColor, QImage, QPainter
        img = QImage(1920, 1080, QImage.Format_RGB32)
        img.fill(QColor(colour))
        if square:
            painter = QPainter(img)
            painter.fillRect(*square, QColor("white"))
            painter.end()
        return img

    def test_fingerprints(self):
        try:
            from gachashift.system import fingerprint_of
            game = fingerprint_of(self.image("#304060"))
            popup = fingerprint_of(self.image("#304060", (700, 400, 520, 280)))  # a dialog appears
        except ImportError:
            self.skipTest("PySide6 isn't installed")
        self.assertEqual(len(game), 64 * 36)
        self.assertIsNone(fingerprint_of(self.image("black")))
        self.assertFalse(looks_different(game, fingerprint_of(self.image("#304060"))))
        self.assertTrue(looks_different(game, popup))


class GameStuckTest(unittest.TestCase):
    def test_remembered_for_the_report(self):
        class G(Game):
            id = "zzz"

        game = G({})
        clock, frames = Clock(), iter([STILL] * 5)
        watch = StallWatch(None, minutes=15, clock=clock, look=lambda: next(frames))
        self.assertFalse(game.stuck(watch))
        clock.now = 16 * 60
        self.assertTrue(game.stuck(watch))
        self.assertEqual(game.stalled, 15)


if __name__ == "__main__":
    unittest.main()
