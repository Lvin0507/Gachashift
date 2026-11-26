"""Each tool's log parser against real logs (tests/logs) and against small format samples.

Run from the repo root:  python -m unittest discover -s tests -v
"""

import json
import os
import pathlib
import tempfile
import unittest

from gachashift import report as R
from gachashift.games.arknights import parse_maa_log
from gachashift.games.endfield import parse_endfield_log
from gachashift.games.genshin import parse_bgi_log
from gachashift.games.wuthering import parse_ww_log
from gachashift.games.zzz import parse_od_log
from gachashift.system import log_size, read_since

LOGS = pathlib.Path(__file__).parent / "logs"


def log(name):
    return (LOGS / name).read_text(encoding="utf-8")


def tasks(rep):
    """{task key: (status, detail)}, which is what a report line shows."""
    return {t.key: (t.status, t.detail) for t in rep.tasks}


def notes(rep):
    return [key for key, _ in rep.notes]


class GenshinTest(unittest.TestCase):
    def parse(self, name):
        return parse_bgi_log(log(name), R.GameReport("genshin"), 10, "exited")

    def test_all_four_and_reward(self):
        rep = self.parse("bettergi_2026-11-13.log")
        self.assertEqual(tasks(rep), {
            "mail": (R.OK, ""), "commissions": (R.OK, "4/4"),
            "dispatch": (R.OK, ""), "daily_reward": (R.OK, "")})
        self.assertEqual(notes(rep), ["note.finished"])

    def test_commission_without_route(self):
        # The progress line is only logged before the commissions run (0/4); the three that
        # finished afterwards must still be counted
        for name in ("bettergi_2026-11-14.log", "bettergi_2026-11-15.log"):
            with self.subTest(name):
                rep = self.parse(name)
                self.assertEqual(tasks(rep)["commissions"], (R.PARTIAL, "3/4"))
                self.assertEqual(tasks(rep)["daily_reward"][0], R.FAIL)
                self.assertIn("note.finished", notes(rep))

    def test_rendered_line(self):
        text = R.render_game(self.parse("bettergi_2026-11-15.log"), "zh")
        self.assertIn("每日委托：⚠️部分完成 (3/4)", text)

    def test_empty_log(self):
        rep = parse_bgi_log("", R.GameReport("genshin"), 0, "not_started")
        self.assertEqual(notes(rep), ["note.no_records"])


class ZenlessTest(unittest.TestCase):
    def test_every_app(self):
        rep = parse_od_log(log("onedragon_2026-11-15.log"), R.GameReport("zzz"), 6)
        self.assertEqual(list(tasks(rep)), [
            "兑换码", "每日签到", "邮件", "录像店营业", "咖啡店", "活跃度奖励", "丽都城募",
            "丽都周纪 (领奖励)"])
        self.assertTrue(all(status == R.OK for status, _ in tasks(rep).values()))
        self.assertEqual(notes(rep), ["note.finished"])

    def test_new_log_file_bigger_than_old(self):
        # 15 Nov: OneDragon started a new log.txt that grew past yesterday's size, and the
        # report lost every app. Reading must restart at the top of the new file.
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "log.txt")
            today = log("onedragon_2026-11-15.log")
            # yesterday's file was nearly as big, so its size points past today's app lines
            pathlib.Path(path).write_text("yesterday\n" * (len(today.encode()) // 12),
                                          encoding="utf-8")
            offset = log_size(path)
            pathlib.Path(path).write_text(today, encoding="utf-8")
            rep = parse_od_log(read_since(path, offset), R.GameReport("zzz"), 6)
        self.assertEqual(len(rep.tasks), 8)

    def test_appended_log(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "log.txt")
            # newline="": write "\n" as it is, also on Windows, where text files get "\r\n"
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("earlier run\n")
            offset = log_size(path)
            with open(path, "a", encoding="utf-8", newline="") as f:
                f.write("this run\n")
            self.assertEqual(read_since(path, offset), "this run\n")


class WutheringTest(unittest.TestCase):
    def test_garden_at_cap(self):
        rep = parse_ww_log(log("okww_2026-11-13.log"), R.GameReport("wuthering"))
        self.assertEqual(tasks(rep), {"garden": (R.OK, "max")})

    def test_task_exception(self):
        # format sample: ok-ww's failure lines, with the error the 16 Nov report showed
        text = ("2026-11-16 07:50:01,000 INFO TaskExecutor GardenTask:exception stopped\n"
                "Exception: 请在大世界并在队伍中开始!\n")
        rep = parse_ww_log(text, R.GameReport("wuthering"))
        self.assertEqual(tasks(rep), {"garden": (R.FAIL, "请在大世界并在队伍中开始!")})


class EndfieldTest(unittest.TestCase):
    """Format samples of MaaEnd's go-service.log (one JSON object per line)."""

    def lines(self, *records):
        return "\n".join(json.dumps(r) for r in records)

    def test_launch_failed(self):
        rep = parse_endfield_log(self.lines({"task": "LaunchGamePC", "message": "failed"}),
                                 R.GameReport("endfield"))
        self.assertEqual(tasks(rep)["LaunchGamePC"][0], R.FAIL)
        self.assertEqual(tasks(rep)["DijiangRewards"][0], R.SKIPPED)

    def test_task_failed_once_of_two(self):
        start = "Checking aspect ratio before task execution"
        rep = parse_endfield_log(self.lines(
            {"task": "LaunchGamePC", "message": "Pretask succeeded"},
            {"entry": "DeliveryJobsMain", "message": start},
            {"entry": "DeliveryJobsMain", "message": "Task failed: target not found"},
            {"entry": "DeliveryJobsMain", "message": start},
        ), R.GameReport("endfield"))
        self.assertEqual(tasks(rep)["DeliveryJobsMain"], (R.FAIL, "1/2"))

    def test_renamed_stash_entry(self):
        start = "Checking aspect ratio before task execution"
        rep = parse_endfield_log(self.lines(
            {"task": "LaunchGamePC", "message": "Pretask succeeded"},
            {"entry": "StashBackpackEntry", "message": start},
        ), R.GameReport("endfield"))
        self.assertEqual(tasks(rep)["StashBackpackMain"], (R.OK, ""))
        self.assertNotIn("StashBackpackEntry", tasks(rep))

    def test_renamed_by_suffix_without_an_alias(self):
        # a rename nobody has added yet: only the last word changed
        start = "Checking aspect ratio before task execution"
        rep = parse_endfield_log(self.lines(
            {"task": "LaunchGamePC", "message": "Pretask succeeded"},
            {"entry": "VisitFriendsEntry", "message": start},
            {"entry": "GiftOperatorTask", "message": start},
            {"entry": "GiftOperatorTask", "message": "Task failed: no gift"},
        ), R.GameReport("endfield"))
        self.assertEqual(tasks(rep)["VisitFriendsMain"], (R.OK, ""))
        self.assertEqual(tasks(rep)["GiftOperatorMain"], (R.FAIL, ""))
        self.assertEqual([t.key for t in rep.tasks if t.new], [])
        self.assertNotIn("note.maybe_renamed", [k for k, _ in rep.notes])

    def test_unrecognised_rename_is_explained(self):
        start = "Checking aspect ratio before task execution"
        rep = parse_endfield_log(self.lines(
            {"task": "LaunchGamePC", "message": "Pretask succeeded"},
            {"entry": "BackpackStorage", "message": start},
        ), R.GameReport("endfield"))
        self.assertEqual(tasks(rep)["StashBackpackMain"][0], R.SKIPPED)
        self.assertIn(("note.maybe_renamed", {"new": "BackpackStorage"}), rep.notes)


class ArknightsTest(unittest.TestCase):
    """Format samples of MAA's gui.log."""

    def test_done(self):
        text = "开始任务: 开始唤醒\n完成任务: 开始唤醒\n开始任务: 自动公招\n已确认招募\n完成任务: 自动公招\n"
        rep = parse_maa_log(text, "done", R.GameReport("arknights"))
        self.assertEqual(tasks(rep), {"开始唤醒": (R.OK, ""), "自动公招": (R.OK, "x1")})

    def test_nothing_logged(self):
        # 16 Nov: the client needed an update, so MAA never got to a task
        rep = parse_maa_log("", "timeout", R.GameReport("arknights"))
        self.assertEqual(notes(rep), ["note.no_records", "note.no_done_marker"])


if __name__ == "__main__":
    unittest.main()
