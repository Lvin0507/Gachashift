"""Which games are tried a second time, and how the second attempt shows in the report."""

import copy
import unittest
from unittest import mock

from gachashift import report as R
from gachashift import runner
from gachashift.config import DEFAULT_CONFIG
from gachashift.games.base import Game


def report(*statuses, notes=()):
    rep = R.GameReport("test")
    for i, status in enumerate(statuses):
        rep.add(f"task{i}", status)
    for key, params in notes:
        rep.note(key, **params)
    return rep


class NeedsRetryTest(unittest.TestCase):
    def test_nothing_done(self):
        self.assertTrue(runner.needs_retry(report(R.FAIL)))                       # 16 Nov, Wuthering Waves
        self.assertTrue(runner.needs_retry(report(notes=[("note.no_records", {}),  # 16 Nov, Arknights
                                                         ("note.no_done_marker", {"reason": "timeout"})])))
        self.assertTrue(runner.needs_retry(report(R.FAIL, R.SKIPPED, R.SKIPPED)))  # Endfield didn't launch
        self.assertTrue(runner.needs_retry(report(notes=[("note.error", {"error": "OSError: x"})])))

    def test_something_done(self):
        self.assertFalse(runner.needs_retry(report(R.OK, R.FAIL)))                # one task failed
        self.assertFalse(runner.needs_retry(report(R.OK, R.PARTIAL, R.FAIL)))     # Genshin, 3/4
        self.assertFalse(runner.needs_retry(report(notes=[("note.finished", {"minutes": 6}),
                                                          ("note.no_task_lines", {})])))
        self.assertFalse(runner.needs_retry(report(R.WARN, notes=[("note.quick_exit", {"minutes": 1})])))

    def test_missing_settings(self):
        self.assertFalse(runner.needs_retry(report(notes=[("note.error", {"error": "missing settings: od_dir"})])))


class RetryRunTest(unittest.TestCase):
    """Run fake games through run_games and look at the reports it returns."""

    def run_with(self, outcomes, only=None, minutes=1):
        """outcomes: game id -> list of reports, one per attempt."""
        calls = {gid: 0 for gid in outcomes}

        def make(gid):
            class Fake(Game):
                id = gid

                def run(self):
                    calls[gid] += 1
                    return copy.deepcopy(outcomes[gid][calls[gid] - 1])
            return Fake

        cfg = copy.deepcopy(DEFAULT_CONFIG)
        for gid in outcomes:
            cfg["games"][gid] = {"enabled": True, "days": list(range(7))}
        clock = iter(range(0, 10 ** 6, minutes * 60))
        with mock.patch.object(runner, "GAMES", [make(g) for g in outcomes]), \
                mock.patch.object(runner.time, "time", lambda: next(clock)):
            reports, stopped = runner.run_games(cfg, only, "en", {"mute": False}, lambda m: None)
        return reports, calls

    def test_failed_game_runs_again_after_the_others(self):
        ok = report(R.OK)
        reports, calls = self.run_with({"arknights": [report(R.FAIL), ok], "zzz": [ok]})
        self.assertEqual(calls, {"arknights": 2, "zzz": 1})
        self.assertEqual([r.tasks[0].status for r in reports], [R.OK, R.OK])  # order kept
        self.assertIn(("note.retried", {}), reports[0].notes)

    def test_still_failing_shows_the_second_attempt(self):
        reports, calls = self.run_with({"wuthering": [report(R.FAIL), report(R.FAIL)]})
        self.assertEqual(calls["wuthering"], 2)
        self.assertIn(("note.retried", {}), reports[0].notes)

    def test_partly_done_is_not_repeated(self):
        reports, calls = self.run_with({"genshin": [report(R.OK, R.FAIL)]})
        self.assertEqual(calls["genshin"], 1)

    def test_single_game_test_run_is_not_repeated(self):
        reports, calls = self.run_with({"zzz": [report(R.FAIL)]}, only="zzz")
        self.assertEqual(calls["zzz"], 1)

    def test_long_first_attempt_is_not_repeated(self):
        reports, calls = self.run_with({"bluearchive": [report(R.WARN)]},
                                       minutes=runner.RETRY_MAX_MINUTES + 20)
        self.assertEqual(calls["bluearchive"], 1)


    def test_waiting_for_the_reset_does_not_count(self):
        # Blue Archive may wait up to two hours for its reset before BAAS even starts; a quick
        # failure after that wait still deserves a second try
        class Waits(Game):
            id = "bluearchive"
            reset = (9, 4)

            def run(self):
                return report(R.FAIL)

        clock = iter(range(0, 10 ** 6, 60))
        waited = lambda *a, **k: [next(clock) for _ in range(90)]  # 90 minutes go by
        with mock.patch.object(runner, "wait_for_reset", waited), \
                mock.patch.object(runner.time, "time", lambda: next(clock)):
            rep = runner.run_game(Waits, {"wait_for_reset": True}, "en")
        self.assertLess(rep.seconds, runner.RETRY_MAX_MINUTES * 60)
        self.assertTrue(runner.needs_retry(rep))


if __name__ == "__main__":
    unittest.main()
