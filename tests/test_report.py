"""The short report sent to phones, and the results remembered for the App's Home page."""

import datetime
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from gachashift import report as R
from gachashift import runner
from gachashift.games.genshin import parse_bgi_log
from gachashift.games.zzz import parse_od_log

LOGS = pathlib.Path(__file__).parent / "logs"


def log(name):
    return (LOGS / name).read_text(encoding="utf-8")


def genshin_15_nov():
    return parse_bgi_log(log("bettergi_2026-11-15.log"), R.GameReport("genshin"), 12, "exited")


def zzz_15_nov():
    return parse_od_log(log("onedragon_2026-11-15.log"), R.GameReport("zzz"), 6)


class CompactReportTest(unittest.TestCase):
    def test_all_done_is_one_line(self):
        self.assertEqual(R.render_compact(zzz_15_nov(), "zh"), "『⚡ 绝区零』✅ 全部完成（8 项） · 6 分钟")

    def test_single_task_keeps_its_detail(self):
        rep = R.GameReport("wuthering")
        rep.add("garden", R.OK, "max")
        rep.note("note.retried")
        self.assertEqual(R.render_compact(rep, "en"),
                         "『🌊 Wuthering Waves』Weekly garden: ✅ Done (max) · second attempt")

    def test_problems_listed_rest_counted(self):
        lines = R.render_compact(genshin_15_nov(), "zh").split("\n")
        self.assertEqual(lines[:4], ["『✨ 原神』", "每日委托：⚠️部分完成 (3/4)",
                                     "每日委托奖励：❌失败 (未领取)", "✅ 其余 2 项完成"])

    def test_needs_you_comes_first(self):
        text = R.render_all([zzz_15_nov(), genshin_15_nov()], "zh", compact=True)
        self.assertTrue(text.startswith("📋 需要你处理\n• 原神：每日委托奖励没领到"))

    def test_nothing_needs_you(self):
        text = R.render_all([zzz_15_nov()], "en", compact=True)
        self.assertTrue(text.startswith("✅ Nothing needs you today"))

    def test_actions(self):
        broken = R.GameReport("arknights")
        broken.note("note.no_records")
        unset = R.GameReport("zzz")
        unset.note("note.error", error="missing settings: od_dir")
        failed = R.GameReport("endfield")
        failed.add("LaunchGamePC", R.OK)
        failed.add("DeliveryJobsMain", R.FAIL, "1/2")
        self.assertEqual(R.actions(broken, "zh"), ["明日方舟：什么都没完成，日志在“历史”页。"])
        self.assertEqual(R.actions(unset, "zh"), ["绝区零：有设置没填，请到“游戏”页补上。"])
        self.assertEqual(R.actions(failed, "zh"), ["终末地：转交委托失败"])

    def test_full_report_unchanged(self):
        # the run log (History) still lists every task
        self.assertEqual(len(R.render_all([zzz_15_nov()], "en").split("\n")), 1 + 8 + 1)


class LastResultsTest(unittest.TestCase):
    def test_saved_per_game_and_kept_for_games_that_did_not_run(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "last_run.json"
            path.write_text(json.dumps({"bluearchive": {"time": "2026-11-20T07:20",
                                                        "outcome": "ok", "failed": 0}}))
            note = R.GameReport("system")
            note.note("note.locked")
            with mock.patch.object(runner, "last_results_file", lambda: path):
                runner.save_last_results([zzz_15_nov(), genshin_15_nov(), note])
                saved = runner.load_last_results()
        self.assertEqual(set(saved), {"bluearchive", "zzz", "genshin"})
        self.assertEqual(saved["zzz"]["outcome"], "ok")
        self.assertEqual((saved["genshin"]["outcome"], saved["genshin"]["failed"]), ("warn", 1))
        self.assertEqual(saved["bluearchive"]["time"], "2026-11-20T07:20")
        self.assertEqual(saved["zzz"]["time"][:10], datetime.date.today().isoformat())


if __name__ == "__main__":
    unittest.main()
