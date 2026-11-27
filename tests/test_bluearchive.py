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
    def play(self, sightings, frozen_from=None, events=None, tap_unfreezes=False, stop_at=None):
        """sightings: what is running in the BAAS folder at each look; the last one stays.
        frozen_from: seconds after the start from which nothing on the screen moves.
        events: seconds since the start -> event.json contents; None means no event.json.
        tap_unfreezes: the tap on a still screen gets things moving again.
        stop_at: seconds after the start at which the player presses Stop."""
        clock = [1000.0]
        looks = iter(sightings)
        last = [sightings[-1]]
        frame = [0]
        self.taps, self.starts = [], []

        def elapsed():
            return clock[0] - 1000

        def processes_in(folder):
            last[0] = next(looks, last[0])
            return last[0]

        def pause(seconds):
            clock[0] += seconds
            if stop_at is not None and elapsed() >= stop_at:
                raise bluearchive.StopRequested()

        def fingerprint():
            if frozen_from is not None and elapsed() >= frozen_from and not (tap_unfreezes and self.taps):
                return (0,) * 4
            frame[0] += 1
            return (10 + frame[0] * 10 % 200,) * 4   # something moves between two looks

        def tap(game):
            self.taps.append(elapsed())
            return True

        def read_events(paths):
            return {"event.json": events(elapsed())} if events else {}

        game = bluearchive.BlueArchive({"baas_dir": "C:/BAAS", "launcher_path": "C:/BA/launcher.exe",
                                        "start_button": [0.85, 0.86]})
        with mock.patch.multiple(bluearchive, launch_and_click=lambda *a, **k: True,
                                 set_windowed=lambda: None, processes_in=processes_in, pause=pause,
                                 kill=lambda names: None, kill_processes=lambda procs: None,
                                 screen_fingerprint=fingerprint, event_paths=lambda folder: ["event.json"],
                                 read_events=read_events), \
                mock.patch.object(bluearchive.BlueArchive, "tap_popup", tap), \
                mock.patch.object(bluearchive.subprocess, "Popen",
                                  lambda *a, **k: self.starts.append(elapsed())), \
                mock.patch.object(bluearchive.subprocess, "CREATE_NEW_CONSOLE", 16, create=True), \
                mock.patch.object(bluearchive.time, "time", lambda: clock[0]), \
                mock.patch.object(bluearchive.time, "sleep", lambda s: None), \
                mock.patch.object(Game, "capture", lambda self, *a: None):
            return game.run()


MIN = 60


class BlueArchiveTest(Runs, unittest.TestCase):
    """No event.json found: the timing decides."""

    def test_long_run_then_stuck_counts_as_done(self):
        # 27 Nov: BAAS did its dailies, then stood on a rewards screen; the report said
        # "nothing got done" and ran it a second time
        rep = self.play([BAAS] + [RUNNING] * 1000, frozen_from=32 * MIN)
        self.assertEqual([(t.key, t.status) for t in rep.tasks], [("baas", R.PARTIAL)])
        key, params = rep.notes[0]
        self.assertEqual(key, "note.baas_stopped_after_work")
        self.assertAlmostEqual(params["minutes"], 32, delta=1)
        self.assertEqual(len(self.taps), 1)   # tapped once before giving up
        self.assertEqual(len(self.starts), 1)  # with no record, BAAS isn't started again
        self.assertFalse(R.nothing_done(rep))

    def test_27_nov_first_attempt(self):
        # BAAS worked about 4 min, then stood still: partly done, run again for the rest
        rep = self.play([BAAS] + [RUNNING] * 1000, frozen_from=4 * MIN)
        self.assertEqual([(t.key, t.status) for t in rep.tasks], [("baas", R.PARTIAL)])
        self.assertTrue(runner.needs_retry(rep))

    def test_stuck_soon_after_starting_is_not_done(self):
        rep = self.play([BAAS] + [RUNNING] * 1000, frozen_from=2 * MIN)
        self.assertEqual([(t.key, t.status) for t in rep.tasks], [("baas", R.WARN)])
        self.assertTrue(R.nothing_done(rep))

    def test_tap_gets_it_moving(self):
        rep = self.play([BAAS] + [RUNNING] * 120 + [[]], frozen_from=10 * MIN, tap_unfreezes=True)
        self.assertEqual([(t.key, t.status) for t in rep.tasks], [("baas", R.OK)])
        self.assertEqual(len(self.taps), 1)
        self.assertAlmostEqual(self.taps[0], 15 * MIN, delta=30)   # after 5 still minutes

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
        self.assertEqual(self.taps, [])

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


DUE, DONE = 900, 10 ** 6   # next_tick before the run (which starts at 1000) and once finished
# the dailies BAAS has switched on in the player's config, in BAAS's order (lowest first)
NAMES = ["竞技场", "咖啡厅", "日程", "查收邮箱", "悬赏通缉", "普通关清体力", "自动制造", "收集奖励"]


def dailies(ticks):
    """event.json with BAAS's own restart (not a daily), a switched-off daily, and NAMES."""
    found = [daily("凌晨四点重启", -2, ticks.get("restart", DUE), func="restart"),
             daily("总力战", 13, DUE, enabled=False)]
    return found + [daily(name, i, ticks.get(name, DUE)) for i, name in enumerate(NAMES)]


def schedule(done_at, already=()):
    """event.json as time goes on: done_at {daily: seconds after the start it is finished}."""
    def events(elapsed):
        ticks = {name: DONE for name in already}
        ticks.update({name: DONE for name, when in done_at.items() if elapsed >= when})
        return dailies(ticks)
    return events


def every(minutes, names, offset=0):
    return {name: (offset + minutes * (i + 1)) * MIN for i, name in enumerate(names)}


class DailyRecordTest(Runs, unittest.TestCase):
    """BAAS's event.json, read while BAAS runs."""

    def tasks(self, rep):
        return [(t.key, t.status) for t in rep.tasks]

    def test_everything_done(self):
        rep = self.play([BAAS] + [RUNNING] * 100 + [[]], events=schedule(every(2, NAMES)))
        self.assertEqual(self.tasks(rep), [(name, R.OK) for name in NAMES])
        self.assertEqual([k for k, _ in rep.notes], ["note.finished"])
        self.assertEqual(R.outcome(rep), "ok")
        self.assertFalse(runner.end_shot_wanted(rep))
        self.assertFalse(runner.needs_retry(rep))
        self.assertEqual((self.taps, len(self.starts)), ([], 1))

    def test_tap_closes_the_reward_popup(self):
        # 27 Nov: rewards claimed, then BAAS stood on 報酬獲得 waiting for a touch
        done = every(1, NAMES[:-1])
        done["收集奖励"] = 17 * MIN   # BAAS goes on once the pop-up is gone
        rep = self.play([BAAS] + [RUNNING] * 100 + [[]], frozen_from=9 * MIN, tap_unfreezes=True,
                        events=schedule(done))
        self.assertEqual(self.tasks(rep), [(name, R.OK) for name in NAMES])
        self.assertEqual(len(self.taps), 1)
        self.assertEqual(len(self.starts), 1)
        self.assertEqual(R.outcome(rep), "ok")

    def test_stuck_twice_on_the_same_daily(self):
        # the tap doesn't help, BAAS is started again, and stops at the same place
        rep = self.play([BAAS] + [RUNNING] * 1000, frozen_from=9 * MIN,
                        events=schedule(every(1, NAMES[:-1])))
        self.assertEqual(self.tasks(rep), [(n, R.OK) for n in NAMES[:-1]] + [("收集奖励", R.FAIL)])
        self.assertEqual(rep.notes, [("note.baas_stuck_twice", {"task": "收集奖励"})])
        self.assertEqual((len(self.taps), len(self.starts)), (2, 2))
        self.assertTrue(runner.end_shot_wanted(rep))
        self.assertFalse(runner.needs_retry(rep))   # the same again later wouldn't help
        self.assertEqual(R.actions(rep, "zh"), ["蔚蓝档案：收集奖励失败"])

    def test_going_round_in_circles_is_restarted(self):
        # the screen keeps moving, but no daily gets finished: BAAS is looking for something
        # it won't find. Starting it again (what the player did by hand) gets it past
        done = every(2, NAMES[:2])
        done.update(every(2, NAMES[2:], offset=25))   # only after the restart at 24 min
        rep = self.play([BAAS] + [RUNNING] * 250 + [[]], events=schedule(done))
        self.assertEqual(self.tasks(rep), [(name, R.OK) for name in NAMES])
        self.assertEqual(len(self.starts), 2)
        self.assertAlmostEqual(self.starts[1], 24 * MIN, delta=30)   # 20 min after 咖啡厅
        self.assertEqual([k for k, _ in rep.notes], ["note.baas_restarted", "note.finished"])
        self.assertEqual(rep.notes[0][1], {"task": "日程"})
        self.assertEqual(R.outcome(rep), "ok")
        line = R.render_compact(rep, "zh")
        self.assertTrue(line.startswith("『📘 蔚蓝档案』✅ 全部完成（8 项）"), line)
        self.assertIn("卡在「日程」后重开过 BAAS", line)

    # looks before the restart at 24 min (each look takes 2 s in the first minute, then 15 s)
    BEFORE_RESTART = [BAAS] + [RUNNING] * 121

    def test_slow_to_come_back_after_the_restart(self):
        done = every(2, NAMES[:2])
        done.update(every(2, NAMES[2:], offset=28))
        rep = self.play(self.BEFORE_RESTART + [BAAS] * 40 + [RUNNING] * 120 + [[]], events=schedule(done))
        self.assertEqual(self.tasks(rep), [(name, R.OK) for name in NAMES])
        self.assertEqual(rep.notes[0], ("note.baas_restarted", {"task": "日程"}))

    def test_never_comes_back_after_the_restart(self):
        rep = self.play(self.BEFORE_RESTART + [BAAS] * 400, events=schedule(every(2, NAMES[:2])))
        self.assertEqual(self.tasks(rep)[2], ("日程", R.FAIL))
        self.assertEqual(rep.notes, [("note.baas_stuck_at", {"task": "日程"})])
        self.assertTrue(runner.needs_retry(rep))   # later, with the game started afresh

    def test_stuck_early_leaves_the_rest_not_run(self):
        rep = self.play([BAAS] + [RUNNING] * 1000, frozen_from=5 * MIN,
                        events=schedule(every(2, NAMES[:2])))
        self.assertEqual(self.tasks(rep)[:4], [("竞技场", R.OK), ("咖啡厅", R.OK), ("日程", R.FAIL),
                                               ("查收邮箱", R.SKIPPED)])
        self.assertEqual(rep.notes, [("note.baas_stuck_twice", {"task": "日程"})])

    def test_baas_gave_up_on_a_daily(self):
        # BAAS stops by itself when a daily fails three times
        rep = self.play([BAAS] + [RUNNING] * 100 + [[]], events=schedule(every(2, NAMES[:4])))
        self.assertEqual(self.tasks(rep)[4], ("悬赏通缉", R.FAIL))
        self.assertEqual(rep.notes, [("note.baas_stopped_at", {"task": "悬赏通缉"})])
        self.assertTrue(runner.needs_retry(rep))

    def test_second_attempt_does_the_rest(self):
        rep = self.play([BAAS] + [RUNNING] * 60 + [[]],
                        events=schedule({"收集奖励": 3 * MIN}, already=NAMES[:-1]))
        self.assertEqual(self.tasks(rep), [(n, R.ALREADY) for n in NAMES[:-1]] + [("收集奖励", R.OK)])
        self.assertEqual(R.outcome(rep), "ok")

    def test_nothing_due_and_baas_left_at_once(self):
        # e.g. BAAS was run by hand earlier: not a warning any more, the record says so
        rep = self.play([BAAS, []], events=schedule({}, already=NAMES))
        self.assertEqual(self.tasks(rep), [(n, R.ALREADY) for n in NAMES])
        self.assertEqual(rep.notes, [])
        self.assertEqual(R.outcome(rep), "ok")

    def test_baas_left_at_once_with_dailies_due(self):
        rep = self.play([BAAS, []], events=schedule({}))
        self.assertEqual(self.tasks(rep), [("baas", R.FAIL)])
        self.assertEqual(rep.notes, [("note.baas_closed_with_dailies", {"count": len(NAMES)})])
        self.assertTrue(runner.needs_retry(rep))

    def test_baas_never_starts_its_tasks(self):
        rep = self.play([BAAS], events=schedule({}))
        self.assertEqual(self.tasks(rep), [("baas", R.FAIL)])
        self.assertEqual(rep.notes[0][0], "note.baas_not_started")

    def test_stopped_by_the_player(self):
        # 27 Nov, 18:45: stopped during 竞技场; the report said only "BAAS dailies: not run"
        with self.assertRaises(bluearchive.StopRequested) as caught:
            self.play([BAAS] + [RUNNING] * 1000, events=schedule(every(2, NAMES[1:3]), already=NAMES[3:5]),
                      stop_at=7 * MIN)
        rep = caught.exception.report
        self.assertEqual(self.tasks(rep), [("竞技场", R.SKIPPED), ("咖啡厅", R.OK), ("日程", R.OK),
                                           ("查收邮箱", R.ALREADY), ("悬赏通缉", R.ALREADY),
                                           ("普通关清体力", R.SKIPPED), ("自动制造", R.SKIPPED),
                                           ("收集奖励", R.SKIPPED)])

    def test_stopped_with_no_record(self):
        with self.assertRaises(bluearchive.StopRequested) as caught:
            self.play([BAAS] + [RUNNING] * 1000, stop_at=3 * MIN)
        self.assertEqual(self.tasks(caught.exception.report), [("baas", R.SKIPPED)])

    def test_stuck_at_different_dailies(self):
        # started again twice already: the third time it ends, and runs again later
        rep = R.GameReport("bluearchive")
        results = [(n, R.OK) for n in NAMES[:5]] + [("普通关清体力", R.FAIL), ("自动制造", R.SKIPPED),
                                                    ("收集奖励", R.SKIPPED)]
        bluearchive.BlueArchive.judge_dailies(rep, results, "stalled", 50, ["日程", "悬赏通缉"], None)
        self.assertEqual([k for k, _ in rep.notes],
                         ["note.baas_restarted", "note.baas_restarted", "note.baas_stuck_at"])
        self.assertTrue(runner.needs_retry(rep))

    def test_texts_exist(self):
        from gachashift.i18n import STRINGS
        for lang in ("en", "zh"):
            for key in ("note.baas_stuck_at", "note.baas_stopped_at", "note.baas_closed_with_dailies",
                        "note.baas_restarted", "note.baas_stuck_twice", "compact.restarted"):
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


class AfterStopTest(unittest.TestCase):
    def test_no_update_looked_for_after_a_stop(self):
        # 27 Nov, 18:45: right after Stop, the cleanup found the launcher open and went
        # looking for an update to click
        from gachashift.games import base
        game = bluearchive.BlueArchive({"launcher_path": "C:/BA/launcher.exe"})
        game.updater = mock.Mock()
        running = {"launcher.exe"}
        with mock.patch.object(base, "process_running", lambda name: name in running):
            with mock.patch.object(base, "stop_requested", lambda: True):
                game.check_launcher()
            game.updater.start_in_run.assert_not_called()
            with mock.patch.object(base, "stop_requested", lambda: False):
                game.check_launcher()
            game.updater.start_in_run.assert_called_once_with(game)


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
