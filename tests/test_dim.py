"""Darkening the screens for a whole run, including a monitor that wakes up partway."""

import copy
import unittest
from unittest import mock

from gachashift import runner, system
from gachashift.config import DEFAULT_CONFIG


class Screens:
    """Fake displays: each holds a gamma ramp, and can refuse ramps darker than a floor."""

    def __init__(self, names, floor=None):
        self.ramps = {n: system._linear_ramp(1.0) for n in names}
        self.floor = floor or {}
        self.sets = []

    def displays(self):
        return list(self.ramps)

    def get(self, name):
        return self.ramps[name]

    def set(self, name, ramp):
        level = system.ramp_level(ramp)
        if level < self.floor.get(name, 0) - 1e-9:
            return False
        self.ramps[name] = ramp
        self.sets.append((name, round(level, 2)))
        return True

    def wake(self, name):
        """A monitor coming out of standby gets its normal gamma back."""
        self.ramps[name] = system._linear_ramp(1.0)


class Brightness:
    def __init__(self, values):
        self.values = list(values)

    def get_brightness(self):
        return list(self.values)

    def set_brightness(self, value, display=None):
        if display is None:
            self.values = [value] * len(self.values)
        else:
            self.values[display] = value


class DimKeeperTest(unittest.TestCase):
    def keeper(self, screens, brightness=None):
        lines = []
        keeper = system.DimKeeper(0.05, displays=screens.displays, get_ramp=screens.get,
                                  set_ramp=screens.set, brightness=brightness, log=lines.append)
        with mock.patch.object(system, "gamma_marker") as marker, \
                mock.patch.object(system.threading, "Thread"):
            marker.return_value.touch = lambda: None
            keeper.start()
        return keeper, lines

    def test_monitor_that_wakes_up_is_darkened_again(self):
        screens = Screens([r"\\.\DISPLAY1", r"\\.\DISPLAY2"])
        keeper, lines = self.keeper(screens)
        self.assertEqual(keeper.reached, {r"\\.\DISPLAY1": 0.05, r"\\.\DISPLAY2": 0.05})
        screens.wake(r"\\.\DISPLAY2")
        keeper.keep_once()
        self.assertAlmostEqual(system.ramp_level(screens.ramps[r"\\.\DISPLAY2"]), 0.05, places=3)
        self.assertIn("darkened again", lines[-1])
        before = len(screens.sets)
        keeper.keep_once()   # nothing changed: nothing is set again
        self.assertEqual(len(screens.sets), before)

    def test_each_screen_keeps_the_level_it_accepted(self):
        screens = Screens(["A", "B"], floor={"B": 0.29})
        keeper, lines = self.keeper(screens)
        self.assertEqual(keeper.reached, {"A": 0.05, "B": 0.3})
        self.assertEqual(lines, ["screen A darkened to 5%", "screen B darkened to 30%"])
        keeper.keep_once()
        self.assertEqual(screens.sets, [("A", 0.05), ("B", 0.3)])  # B isn't pushed below 30%

    def test_a_screen_that_appears_later_is_darkened(self):
        screens = Screens(["A"])
        keeper, lines = self.keeper(screens)
        screens.ramps["B"] = system._linear_ramp(1.0)   # switched on after the start
        keeper.keep_once()
        self.assertAlmostEqual(system.ramp_level(screens.ramps["B"]), 0.05, places=3)

    def test_backlight_set_again_and_the_old_level_kept(self):
        screens = Screens(["A", "B"])
        brightness = Brightness([80, 100])
        keeper, _ = self.keeper(screens, brightness)
        self.assertEqual((brightness.values, keeper.originals), ([5, 5], [80, 100]))
        brightness.values[1] = 100   # the monitor woke up at full brightness
        keeper.keep_once()
        self.assertEqual(brightness.values, [5, 5])
        self.assertEqual(keeper.originals, [80, 100])


class ManualDimTest(unittest.TestCase):
    def dim_used(self, **kwargs):
        seen = {}

        def fake_run_games(cfg, only, lang, opts, log, dim=False, **rest):
            seen["dim"] = dim
            return [], False

        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["options"]["dim_screen"] = kwargs.pop("dim_screen", False)
        with mock.patch.multiple(runner, run_games=fake_run_games, wait_for_unlock=lambda: True,
                                 save_last_results=lambda r: None, unfinished_run=lambda: None,
                                 seconds_since_input=lambda: 10 ** 6), \
                mock.patch.object(runner, "running_file") as running, \
                mock.patch.object(runner, "prune_screenshots", lambda: None), \
                mock.patch.object(runner, "screenshot_folder", lambda: "shots"):
            running.return_value.write_text = lambda text: None
            running.return_value.unlink = lambda: None
            runner.run_all(cfg, allow_shutdown=False, send=False, log=lambda m: None, **kwargs)
        return seen["dim"]

    def test_run_page_switch_darkens_a_run_started_by_hand(self):
        self.assertTrue(self.dim_used(dim=True))

    def test_hand_started_run_stays_bright_by_default(self):
        self.assertFalse(self.dim_used(dim_screen=True))

    def test_scheduled_run_follows_general(self):
        self.assertTrue(self.dim_used(ask_first=True, dim_screen=True))


if __name__ == "__main__":
    unittest.main()
