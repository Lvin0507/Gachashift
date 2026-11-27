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
from gachashift.games.genshin import count_commissions, parse_bgi_log
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

    def test_commission_list_without_progress_line(self):
        # 27 Nov, commission script 1.0.5: no "当前每日委托奖励进度" line, only the list of the
        # four (three already done) and the one it then finished
        rep = self.parse("bettergi_2026-11-27.log")
        self.assertEqual(tasks(rep), {
            "commissions": (R.OK, "4/4"), "dispatch": (R.NOTHING, ""), "daily_reward": (R.OK, "")})
        self.assertEqual(notes(rep), ["note.finished"])

    def test_misread_commission_and_a_domain_cut_short(self):
        # one commission's name misread ("鸿子习惯："), so skipped as unsupported; the game
        # was closed during the first domain
        rep = self.parse("bettergi_2026-11-27_mondstadt.log")
        self.assertEqual(tasks(rep)["commissions"], (R.PARTIAL, "3/4"))
        self.assertEqual(tasks(rep)["dispatch"], (R.OK, ""))
        self.assertEqual(tasks(rep)["domain"], (R.FAIL, ""))

    def test_domain_stopped_after_one_reward(self):
        rep = self.parse("bettergi_2026-11-27_domain.log")
        self.assertEqual(tasks(rep)["domain"], (R.PARTIAL, "×1"))

    def domain(self, *lines):
        text = "\n".join(["自动秘境任务：执行", *lines])
        return tasks(parse_bgi_log(text, R.GameReport("genshin"), 30, "exited"))["domain"]

    def test_domain_resin_used_up(self):
        claim_old = '"自动秘境"：使用 "原粹树脂", 数量：20'
        claim_new = "自动秘境：使用 浓缩树脂，消耗：1"
        self.assertEqual(self.domain(claim_old, claim_old, claim_new,
                                     "体力耗尽或者设置轮次已达标，结束自动秘境"), (R.OK, "×3"))

    def test_config_with_domains_only(self):
        # a one-dragon config that only spends resin: no commission reward to warn about
        text = "\n".join(["自动秘境任务：执行", '"自动秘境"：使用 "原粹树脂", 数量：20',
                          "体力耗尽或者设置轮次已达标，结束自动秘境", "一条龙和配置组任务结束"])
        rep = parse_bgi_log(text, R.GameReport("genshin"), 30, "exited")
        self.assertEqual(tasks(rep), {"domain": (R.OK, "×1")})
        self.assertEqual(R.outcome(rep), "ok")

    def test_reward_task_that_said_nothing(self):
        rep = parse_bgi_log('→ "前往冒险家协会领取奖励" 开始', R.GameReport("genshin"), 5, "exited")
        self.assertEqual(tasks(rep)["daily_reward"][0], R.WARN)

    def test_six_rewards_asked_but_resin_for_one(self):
        # 28 Nov 00:03: set to 6 rewards, 20 resin left: one reward, then BetterGI ended it
        rep = self.parse("bettergi_2026-11-28_six_rewards.log")
        self.assertEqual(tasks(rep)["domain"], (R.PARTIAL, "1/6"))

    def test_six_rewards_done(self):
        lines = ['"自动秘境"：使用 "原粹树脂", 数量：20\n自动秘境："原粹树脂" 刷取 %d/6' % n for n in range(1, 7)]
        text = "\n".join(["自动秘境任务：执行", *lines, '当前刷取情况："原粹树脂(6/6)"',
                          "体力耗尽或者设置轮次已达标，结束自动秘境"])
        self.assertEqual(tasks(parse_bgi_log(text, R.GameReport("genshin"), 15, "exited"))["domain"],
                         (R.OK, "6/6"))

    def test_rewards_count_from_newer_bettergi(self):
        text = "\n".join(["自动秘境任务：执行", "自动秘境：使用 原粹树脂，消耗：20",
                          "自动秘境任务结果：Success，秘境流程已结束：领奖 1/1 次",
                          "体力耗尽或者设置轮次已达标，结束自动秘境"])
        self.assertEqual(tasks(parse_bgi_log(text, R.GameReport("genshin"), 5, "exited"))["domain"],
                         (R.OK, "1/1"))

    def test_paused_because_the_game_was_not_in_front(self):
        # 27 Nov 23:59: Claude's window was in front, BetterGI paused a minute and gave up
        rep = self.parse("bettergi_2026-11-27_focus.log")
        self.assertEqual(tasks(rep)["domain"], (R.FAIL, ""))
        self.assertIn(("note.bgi_focus", {"seconds": 60, "window": "claude"}), rep.notes)

    def test_short_pause_that_did_no_harm(self):
        text = "\n".join(["当前获取焦点的窗口为: explorer，不是原神，暂停", '检查每日奖励结果："今日奖励已领取"'])
        self.assertNotIn("note.bgi_focus", notes(parse_bgi_log(text, R.GameReport("genshin"), 5, "exited")))

    def test_domain_with_no_resin(self):
        self.assertEqual(self.domain('自动秘境：检测到树脂不足提示："原粹树脂不足"'), (R.NOTHING, ""))

    def test_commissions_listed_again_are_not_counted_twice(self):
        listing = lambda states: "\n".join(f"委托 {i} | 委托{i} | {s} | Basic | 蒙德 | - | 坐标: -"
                                           for i, s in enumerate(states, 1))
        text = "\n".join([listing(["已完成", "未完成", "未完成", "未知"]), "委托执行成功：委托2",
                          listing(["已完成", "已完成", "未完成", "未知"]), "委托执行成功：委托3"])
        self.assertEqual(count_commissions(text), (3, 4))


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

    def test_english_ui(self):
        # ok-ww writes its log in its UI language
        text = ("2026-11-20 06:00:01,000 INFO TaskExecutor GardenTask:Garden current: [6000_1.00]\n"
                "2026-11-20 06:00:01,000 INFO TaskExecutor GardenTask:Garden task completed; limit reached\n")
        rep = parse_ww_log(text, R.GameReport("wuthering"))
        self.assertEqual(tasks(rep), {"garden": (R.OK, "max")})

    def test_traditional_chinese_ui(self):
        text = "GardenTask:當前樂園進度：[]\nGardenTask:樂園任務完成, 已達到上限\n"
        rep = parse_ww_log(text, R.GameReport("wuthering"))
        self.assertEqual(tasks(rep), {"garden": (R.OK, "")})


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

    def test_english_ui(self):
        # MAA writes gui.log in its UI language; English task names have spaces and a
        # no-break space follows the colon
        text = ("[2026-11-20 05:00:00][INF] Start task:\u00a0Wake Up\n"
                "[2026-11-20 05:01:00][INF] Complete task:\u00a0Wake Up\n(in 0h 1m 0s)\n"
                "[2026-11-20 05:01:00][INF] Start task:\u00a0Auto Recruit\n"
                "Recruit confirm\nRecruit confirm\n"
                "[2026-11-20 05:03:00][INF] Complete task:\u00a0Auto Recruit\n"
                "[2026-11-20 05:03:00][INF] Start task:\u00a0Combat\n")
        rep = parse_maa_log(text, "timeout", R.GameReport("arknights"))
        self.assertEqual(tasks(rep), {"Wake Up": (R.OK, ""), "Auto Recruit": (R.OK, "x2"),
                                      "Combat": (R.FAIL, "")})

    def test_japanese_ui(self):
        text = "タスク開始: 公開求人\n募集を行いました\nタスク完了: 公開求人\nすべてのタスクが完了しました！\n"
        rep = parse_maa_log(text, "done", R.GameReport("arknights"))
        self.assertEqual(tasks(rep), {"公開求人": (R.OK, "x1")})

    def test_nothing_logged(self):
        # 16 Nov: the client needed an update, so MAA never got to a task
        rep = parse_maa_log("", "timeout", R.GameReport("arknights"))
        self.assertEqual(notes(rep), ["note.no_records", "note.no_done_marker"])


if __name__ == "__main__":
    unittest.main()
