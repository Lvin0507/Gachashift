"""How a Blue Archive run is judged from the BAAS processes Gachashift can see."""

import unittest
from unittest import mock

from gachashift import report as R
from gachashift import runner
from gachashift.games import bluearchive
from gachashift.games.base import Game


class P:
    def __init__(self, name):
        self.info = {"name": name}


BAAS = [P("BlueArchiveAutoScript.exe")]
RUNNING = [P("BlueArchiveAutoScript.exe"), P("pythonw.exe")]


class BlueArchiveTest(unittest.TestCase):
    def play(self, sightings, seconds_per_look=2, stuck_after=None):
        """sightings: what is running in the BAAS folder at each look; the last one stays.
        stuck_after: seconds after which the screen counts as still for 15 min."""
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
                mock.patch.object(Game, "stuck", lambda game, watch: self.still(game, clock, stuck_after)):
            return game.run()

    @staticmethod
    def still(game, clock, stuck_after):
        if stuck_after is not None and clock[0] - 1000 >= stuck_after:
            game.stalled = 15
            return True
        return False

    def test_long_run_then_stuck_counts_as_done(self):
        # 27 Nov: BAAS did its dailies, then stood on a rewards screen until the stall check
        # ended it; the report said "nothing got done" and ran it a second time
        rep = self.play([BAAS] + [RUNNING] * 1000, stuck_after=40 * 60)
        self.assertEqual([(t.key, t.status) for t in rep.tasks], [("baas", R.PARTIAL)])
        key, params = rep.notes[0]
        self.assertEqual(key, "note.baas_stopped_after_work")
        self.assertAlmostEqual(params["minutes"], 25, delta=1)   # 40 min run, the last 15 still
        self.assertFalse(R.nothing_done(rep))

    def test_27_nov_first_attempt(self):
        # BAAS started 05:25:41 and was ended at 05:44:28 for 15 still minutes: about 4 min of
        # work, then stuck. Partly done, and run again for the rest
        rep = self.play([BAAS] + [RUNNING] * 1000, stuck_after=18 * 60 + 47)
        self.assertEqual([(t.key, t.status) for t in rep.tasks], [("baas", R.PARTIAL)])
        self.assertTrue(runner.needs_retry(rep))

    def test_stuck_soon_after_starting_is_not_done(self):
        rep = self.play([BAAS] + [RUNNING] * 1000, stuck_after=17 * 60)
        self.assertEqual([(t.key, t.status) for t in rep.tasks], [("baas", R.WARN)])
        self.assertTrue(R.nothing_done(rep))

    def test_restart_while_updating_is_not_an_exit(self):
        # BAAS closes and starts again when it updates itself: a short gap isn't the end
        rep = self.play([BAAS, RUNNING] + [[]] * 10 + [BAAS] + [RUNNING] * 200 + [[]])
        self.assertEqual([(t.key, t.status) for t in rep.tasks], [("baas", R.OK)])

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


class RetryWordingTest(unittest.TestCase):
    def test_stuck_partway_is_retried_and_says_so(self):
        import copy
        from gachashift.config import DEFAULT_CONFIG
        attempts = []

        class Fake(Game):
            id = "bluearchive"

            def run(self):
                attempts.append(1)
                rep = self.new_report()
                rep.add("baas", R.PARTIAL)
                rep.note("note.baas_stopped_after_work", minutes=4 if len(attempts) == 1 else 11)
                return rep

        cfg = copy.deepcopy(DEFAULT_CONFIG)
        for gid in cfg["games"]:
            cfg["games"][gid] = {"enabled": gid == "bluearchive", "days": list(range(7))}
        lines = []
        with mock.patch.object(runner, "ordered", lambda cfg: [Fake]):
            reports, _ = runner.run_games(cfg, None, "en", {"mute": False}, lines.append)
        self.assertEqual(len(attempts), 2)
        self.assertIn("got stuck partway", lines[-1])
        notes = [key for key, _ in reports[0].notes]
        self.assertEqual(notes, ["note.baas_stopped_after_work", "note.retried_rest"])
        self.assertEqual(R.outcome(reports[0]), "warn")
        self.assertEqual(R.actions(reports[0], "en"), [])   # not "nothing got done"


if __name__ == "__main__":
    unittest.main()
