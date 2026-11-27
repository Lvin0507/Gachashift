"""How a Blue Archive run is judged: from BAAS's own record of finished dailies (event.json)
when it can be read, otherwise from the BAAS processes Gachashift can see."""

import json
import os
import tempfile
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


class Runs:
    def play(self, sightings, seconds_per_look=2, stuck_after=None, events=None):
        """sightings: what is running in the BAAS folder at each look; the last one stays.
        stuck_after: seconds after which the screen counts as still for 15 min.
        events: (before, after) event.json contents; None means no event.json was found."""
        clock = [1000.0]
        records = iter([{"event.json": e} for e in events] if events else [])
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
                                 kill=lambda names: None, kill_processes=lambda procs: None,
                                 event_paths=lambda folder: ["event.json"],
                                 read_events=lambda paths: next(records, {})), \
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


class BlueArchiveTest(Runs, unittest.TestCase):
    """No event.json found: the timing decides."""

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


def daily(name, priority, tick, func=None, enabled=True):
    return {"enabled": enabled, "priority": priority, "next_tick": tick, "event_name": name,
            "func_name": func or name}


DUE, DONE = 900, 5000   # next_tick before the run (1000) and after it
# the dailies BAAS has switched on in the player's config, in BAAS's order (lowest first)
NAMES = ["竞技场", "咖啡厅", "日程", "查收邮箱", "悬赏通缉", "普通关清体力", "自动制造", "收集奖励"]


def dailies(ticks):
    """event.json with BAAS's own restart (not a daily), a switched-off daily, and NAMES."""
    found = [daily("凌晨四点重启", -2, ticks.get("restart", DUE), func="restart"),
             daily("总力战", 13, DUE, enabled=False)]
    return found + [daily(name, i, ticks.get(name, DUE)) for i, name in enumerate(NAMES)]


class DailyRecordTest(Runs, unittest.TestCase):
    """BAAS's event.json, read before and after the run."""

    def tasks(self, rep):
        return [(t.key, t.status) for t in rep.tasks]

    def test_everything_done(self):
        rep = self.play([BAAS] + [RUNNING] * 100 + [[]],
                        events=(dailies({}), dailies({name: DONE for name in NAMES})))
        self.assertEqual(self.tasks(rep), [(name, R.OK) for name in NAMES])
        self.assertEqual([k for k, _ in rep.notes], ["note.finished"])
        self.assertEqual(R.outcome(rep), "ok")
        self.assertFalse(runner.end_shot_wanted(rep))
        self.assertFalse(runner.needs_retry(rep))

    def test_stuck_on_the_last_daily(self):
        # 27 Nov: BAAS stood on a 報酬獲得 screen until the stall check closed it
        after = dailies({name: DONE for name in NAMES[:-1]})
        rep = self.play([BAAS] + [RUNNING] * 1000, stuck_after=40 * 60, events=(dailies({}), after))
        self.assertEqual(self.tasks(rep), [(n, R.OK) for n in NAMES[:-1]] + [("收集奖励", R.FAIL)])
        self.assertEqual(rep.notes, [("note.baas_stuck_at", {"task": "收集奖励"})])
        self.assertFalse(R.nothing_done(rep))
        self.assertTrue(runner.end_shot_wanted(rep))   # the picture shows where it stopped
        self.assertTrue(runner.needs_retry(rep))       # a second run does what is left

    def test_stuck_early_leaves_the_rest_not_run(self):
        after = dailies({"竞技场": DONE, "咖啡厅": DONE})
        rep = self.play([BAAS] + [RUNNING] * 1000, stuck_after=20 * 60, events=(dailies({}), after))
        self.assertEqual(self.tasks(rep)[:4], [("竞技场", R.OK), ("咖啡厅", R.OK), ("日程", R.FAIL),
                                               ("查收邮箱", R.SKIPPED)])
        self.assertEqual(rep.notes, [("note.baas_stuck_at", {"task": "日程"})])

    def test_baas_gave_up_on_a_daily(self):
        # BAAS stops by itself when a daily fails three times
        after = dailies({name: DONE for name in NAMES[:4]})
        rep = self.play([BAAS] + [RUNNING] * 100 + [[]], events=(dailies({}), after))
        self.assertEqual(self.tasks(rep)[4], ("悬赏通缉", R.FAIL))
        self.assertEqual(rep.notes, [("note.baas_stopped_at", {"task": "悬赏通缉"})])
        self.assertTrue(runner.needs_retry(rep))

    def test_second_attempt_does_the_rest(self):
        before = dailies({name: DONE for name in NAMES[:-1]})
        rep = self.play([BAAS] + [RUNNING] * 60 + [[]],
                        events=(before, dailies({name: DONE for name in NAMES})))
        self.assertEqual(self.tasks(rep), [(n, R.ALREADY) for n in NAMES[:-1]] + [("收集奖励", R.OK)])
        self.assertEqual(R.outcome(rep), "ok")

    def test_nothing_due_and_baas_left_at_once(self):
        # e.g. BAAS was run by hand earlier: not a warning any more, the record says so
        done = dailies({name: DONE for name in NAMES})
        rep = self.play([BAAS, []], events=(done, done))
        self.assertEqual(self.tasks(rep), [(n, R.ALREADY) for n in NAMES])
        self.assertEqual(rep.notes, [])
        self.assertEqual(R.outcome(rep), "ok")

    def test_baas_left_at_once_with_dailies_due(self):
        rep = self.play([BAAS, []], events=(dailies({}), dailies({})))
        self.assertEqual(self.tasks(rep), [("baas", R.FAIL)])
        self.assertEqual(rep.notes, [("note.baas_closed_with_dailies", {"count": len(NAMES)})])
        self.assertTrue(runner.needs_retry(rep))

    def test_baas_never_starts_its_tasks(self):
        rep = self.play([BAAS], events=(dailies({}), dailies({})))
        self.assertEqual(self.tasks(rep), [("baas", R.FAIL)])
        self.assertEqual(rep.notes[0][0], "note.baas_not_started")

    def test_texts_exist(self):
        from gachashift.i18n import STRINGS
        for lang in ("en", "zh"):
            for key in ("note.baas_stuck_at", "note.baas_stopped_at", "note.baas_closed_with_dailies"):
                self.assertIn(key, STRINGS[lang], (lang, key))


class EventFilesTest(unittest.TestCase):
    def test_config_that_runs_on_startup(self):
        with tempfile.TemporaryDirectory() as baas:
            for name, autostart in (("jp", True), ("global", False)):
                folder = os.path.join(baas, "config", name)
                os.makedirs(folder)
                with open(os.path.join(folder, "config.json"), "w", encoding="utf-8") as f:
                    json.dump({"autostart": autostart}, f)
                with open(os.path.join(folder, "event.json"), "w", encoding="utf-8") as f:
                    json.dump(dailies({}), f, ensure_ascii=False)
            paths = bluearchive.event_paths(baas)
            self.assertEqual(paths, [os.path.join(baas, "config", "jp", "event.json")])
            self.assertEqual(len(bluearchive.read_events(paths + ["missing.json"])[paths[0]]),
                             len(NAMES) + 2)


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
