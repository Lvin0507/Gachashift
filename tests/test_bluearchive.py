"""How a Blue Archive run is judged from the BAAS processes Gachashift can see."""

import unittest
from unittest import mock

from gachashift import report as R
from gachashift.games import bluearchive
from gachashift.games.base import Game


class P:
    def __init__(self, name):
        self.info = {"name": name}


BAAS = [P("BlueArchiveAutoScript.exe")]
RUNNING = [P("BlueArchiveAutoScript.exe"), P("pythonw.exe")]


class BlueArchiveTest(unittest.TestCase):
    def play(self, sightings, seconds_per_look=2):
        """sightings: what is running in the BAAS folder at each look; the last one stays."""
        clock = [1000.0]
        looks = iter(sightings)
        last = [sightings[-1]]

        def processes_in(folder):
            last[0] = next(looks, last[0])
            return last[0]

        def pause(seconds):
            clock[0] += seconds

        game = bluearchive.BlueArchive({"baas_dir": "C:/BAAS", "launcher_path": "C:/BA/launcher.exe",
                                        "start_button": [0.85, 0.86]})
        with mock.patch.multiple(bluearchive, launch_and_click=lambda *a, **k: True,
                                 set_windowed=lambda: None, processes_in=processes_in, pause=pause,
                                 kill=lambda names: None, kill_processes=lambda procs: None), \
                mock.patch.object(bluearchive.subprocess, "Popen", lambda *a, **k: None), \
                mock.patch.object(bluearchive.subprocess, "CREATE_NEW_CONSOLE", 16, create=True), \
                mock.patch.object(bluearchive.time, "time", lambda: clock[0]), \
                mock.patch.object(bluearchive.time, "sleep", lambda s: None), \
                mock.patch.object(Game, "capture", lambda self, *a: None), \
                mock.patch.object(Game, "stuck", lambda self, watch: False):
            return game.run()

    def test_baas_closed_within_seconds(self):
        # nothing due: BAAS came and went between two looks, its task runner never seen
        rep = self.play([BAAS, []])
        self.assertEqual([(t.key, t.status) for t in rep.tasks], [("baas", R.WARN)])
        self.assertEqual(rep.notes[0][0], "note.baas_closed_early")
        self.assertNotIn("note.not_started", [k for k, _ in rep.notes])

    def test_quick_run_is_caught_by_frequent_looks(self):
        rep = self.play([BAAS, RUNNING, RUNNING, BAAS, []])
        self.assertEqual(rep.notes[0][0], "note.quick_exit")

    def test_full_run(self):
        rep = self.play([BAAS] + [RUNNING] * 100 + [[]])
        self.assertEqual([(t.key, t.status) for t in rep.tasks], [("baas", R.OK)])

    def test_baas_never_starts_its_tasks(self):
        rep = self.play([BAAS])
        self.assertEqual([(t.key, t.status) for t in rep.tasks], [("baas", R.FAIL)])
        self.assertEqual(rep.notes[0][0], "note.baas_not_started")

    def test_texts_exist(self):
        from gachashift.i18n import STRINGS
        for lang in ("en", "zh"):
            for key in ("note.baas_closed_early", "note.baas_not_started"):
                self.assertIn(key, STRINGS[lang], (lang, key))


if __name__ == "__main__":
    unittest.main()
