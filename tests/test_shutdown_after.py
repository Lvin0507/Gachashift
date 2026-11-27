"""The Run page's "shut down when done" switch: only for that run, and never after a stop."""

import copy
import unittest
from unittest import mock

from gachashift import runner
from gachashift.config import DEFAULT_CONFIG


class ShutdownAfterTest(unittest.TestCase):
    def shut_down(self, general=True, stopped=False, **kwargs):
        calls = []
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["options"]["shutdown"] = general
        with mock.patch.multiple(runner, run_games=lambda *a, **k: ([], stopped),
                                 wait_for_unlock=lambda: True, save_last_results=lambda r: None,
                                 unfinished_run=lambda: None, seconds_since_input=lambda: 10 ** 6,
                                 shutdown=lambda: calls.append(1)), \
                mock.patch.object(runner, "running_file") as running, \
                mock.patch.object(runner, "prune_screenshots", lambda: None), \
                mock.patch.object(runner, "screenshot_folder", lambda: "shots"):
            running.return_value.write_text = lambda text: None
            running.return_value.unlink = lambda: None
            runner.run_all(cfg, send=False, log=lambda m: None, **kwargs)
        return bool(calls)

    def test_switch_on(self):
        self.assertTrue(self.shut_down(allow_shutdown=False, shutdown_after=True))

    def test_switch_on_with_general_off(self):
        self.assertTrue(self.shut_down(general=False, allow_shutdown=False, shutdown_after=True))

    def test_stopped(self):
        self.assertFalse(self.shut_down(stopped=True, allow_shutdown=False, shutdown_after=True))

    def test_run_by_hand_keeps_the_pc_on(self):
        self.assertFalse(self.shut_down(allow_shutdown=False))

    def test_scheduled_run_follows_general(self):
        self.assertTrue(self.shut_down(ask_first=True))
        self.assertFalse(self.shut_down(general=False, ask_first=True))

    def test_texts_exist(self):
        from gachashift.i18n import STRINGS
        for lang in ("en", "zh"):
            for key in ("run.shutdown", "run.shutdown_hint"):
                self.assertIn(key, STRINGS[lang], (lang, key))


if __name__ == "__main__":
    unittest.main()
