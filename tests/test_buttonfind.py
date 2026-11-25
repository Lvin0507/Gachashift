"""Finding a launcher's start button in a picture, and clicking it when the saved spot fails."""

import random
import unittest
from unittest import mock

from gachashift import buttonfind, system

W, H = 192, 108


def picture(button=None, colour=(255, 204, 51), decoys=True, seed=1):
    """A launcher-like picture: noisy, colourful art everywhere, a button in the lower right."""
    rnd = random.Random(seed)
    pixels = []
    for y in range(H):
        for x in range(W):
            # art: smooth colour bands with noise, like a game illustration
            base = ((x * 3 + y * 5) % 256, (x * 7) % 256, (y * 11 + 60) % 256)
            pixels.append(tuple(max(0, min(255, c + rnd.randint(-40, 40))) for c in base))

    def fill(x0, y0, x1, y1, rgb):
        for y in range(int(y0 * H), int(y1 * H)):
            for x in range(int(x0 * W), int(x1 * W)):
                pixels[y * W + x] = rgb

    if decoys:
        fill(0.05, 0.05, 0.6, 0.4, (40, 120, 230))   # a big blue sky, but not in the corner
        fill(0.55, 0.62, 0.58, 0.67, (230, 30, 30))   # a small red icon in the corner
        fill(0.6, 0.55, 0.64, 0.95, (30, 200, 90))    # a tall green strip: wrong shape
    if button:
        x0, y0, x1, y1 = button
        fill(x0, y0, x1, y1, colour)
        # white letters in the middle of the button: short strokes with gaps between them
        middle = (y0 + y1) / 2
        x = x0 + 0.03
        while x < x1 - 0.04:
            fill(x, middle - 0.015, x + 0.008, middle + 0.015, (255, 255, 255))
            x += 0.02
    return pixels


class FindTest(unittest.TestCase):
    def test_hoyoplay_like(self):
        found = buttonfind.find_button(picture((0.78, 0.82, 0.92, 0.9)), W, H)
        self.assertAlmostEqual(found[0], 0.85, delta=0.02)
        self.assertAlmostEqual(found[1], 0.86, delta=0.02)

    def test_blue_button(self):
        found = buttonfind.find_button(picture((0.76, 0.83, 0.94, 0.91), colour=(40, 140, 255)), W, H)
        self.assertAlmostEqual(found[0], 0.85, delta=0.02)
        self.assertAlmostEqual(found[1], 0.87, delta=0.02)

    def test_no_button(self):
        self.assertIsNone(buttonfind.find_button(picture(None), W, H))

    def test_dark_button_is_not_a_button(self):
        found = buttonfind.find_button(picture((0.78, 0.82, 0.92, 0.9), colour=(60, 50, 20), decoys=False), W, H)
        self.assertIsNone(found)

    def test_far_apart(self):
        self.assertTrue(buttonfind.far_apart((0.85, 0.86), (0.5, 0.9)))
        self.assertFalse(buttonfind.far_apart((0.85, 0.86), (0.852, 0.859)))
        self.assertFalse(buttonfind.far_apart(None, (0.85, 0.86)))


class ClickTest(unittest.TestCase):
    """launch_and_click with the Windows parts faked."""

    def run_launcher(self, button, found, starts_after_clicks_at=None):
        clicks = []

        def click(hwnd, fx, fy):
            clicks.append((fx, fy))
            return True

        def running(name):
            return starts_after_clicks_at is not None and starts_after_clicks_at in clicks

        with mock.patch.multiple(system, make_dpi_aware=lambda: None, pause=lambda s: None,
                                 process_running=running, main_window_of=lambda exe: 1,
                                 bring_to_front=lambda hwnd: True, click_in_window=click), \
                mock.patch.object(system.time, "time", side_effect=list(range(0, 600, 10)) * 2):
            ok = system.launch_and_click(lambda: None, "HYP.exe", button, "Game.exe",
                                         wait_after=0, timeout=100, find=lambda hwnd: found)
        return ok, clicks

    def test_calibrated_spot_works(self):
        ok, clicks = self.run_launcher((0.85, 0.86), (0.5, 0.5), starts_after_clicks_at=(0.85, 0.86))
        self.assertTrue(ok)
        self.assertEqual(clicks, [(0.85, 0.86)])

    def test_switches_to_the_found_button(self):
        ok, clicks = self.run_launcher((0.85, 0.86), (0.7, 0.9), starts_after_clicks_at=(0.7, 0.9))
        self.assertTrue(ok)
        self.assertEqual(clicks, [(0.85, 0.86)] * 3 + [(0.7, 0.9)])

    def test_nothing_calibrated(self):
        ok, clicks = self.run_launcher(None, (0.84, 0.88), starts_after_clicks_at=(0.84, 0.88))
        self.assertTrue(ok)
        self.assertEqual(clicks, [(0.84, 0.88)])

    def test_nothing_found_and_nothing_calibrated(self):
        ok, clicks = self.run_launcher(None, None)
        self.assertFalse(ok)
        self.assertEqual(clicks, [])


if __name__ == "__main__":
    unittest.main()
