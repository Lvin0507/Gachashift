"""Logs read while the tools run: following a file OneDragon replaces, the stall check not
spoiling the final read, and the failure pictures for MAA and OneDragon."""

import os
import tempfile
import unittest
from pathlib import Path

from gachashift import report as R
from gachashift import system
from gachashift.games.arknights import MaaFailures
from gachashift.games.base import LiveLog
from gachashift.games.genshin import BetterGIFailures, FocusWatch
from gachashift.games.zzz import OneDragonFailures, parse_od_log

LOGS = Path(__file__).parent / "logs"


def od_log():
    return (LOGS / "onedragon_2026-11-27.log").read_text(encoding="utf-8")


class Lines(LiveLog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen = []

    def line(self, raw):
        self.seen.append(raw)


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "log.txt")

    def write(self, text, mode="w"):
        with open(self.path, mode, encoding="utf-8", newline="") as f:
            f.write(text)


class StallCheckTest(Folder):
    def test_new_log_file_with_the_stall_check_running(self):
        # 27 Nov: OneDragon began a new log.txt; the stall check, run every 15 s, remembered
        # the new file's first bytes, so the final read took it for the old file and read
        # only from the old size on: "finished", but not one app
        today = od_log()
        self.write("[17:00:00.000] yesterday's session\n" * (len(today.encode()) // 38))
        offset = system.log_size(self.path)
        self.write(today)
        system.StallWatch(self.path, look=lambda: None).stuck()
        rep = parse_od_log(system.read_since(self.path, offset), R.GameReport("zzz"), 5)
        self.assertEqual(len(rep.tasks), 8)


class OneDragonLogTest(unittest.TestCase):
    def test_27_nov(self):
        rep = parse_od_log(od_log(), R.GameReport("zzz"), 5)
        statuses = {t.key: t.status for t in rep.tasks}
        self.assertEqual(statuses.pop("活跃度奖励"), R.FAIL)
        self.assertEqual(list(statuses), ["兑换码", "每日签到", "邮件", "录像店营业", "咖啡店", "丽都城募",
                                          "丽都周纪 (领奖励)"])
        self.assertTrue(all(s == R.OK for s in statuses.values()))
        self.assertEqual([k for k, _ in rep.notes], ["note.finished"])


class LiveLogTest(Folder):
    def test_reads_complete_lines_only(self):
        self.write("one\ntw")
        live = Lines(self.path)
        live.poll()
        self.write("o\nthree\n", "a")
        live.poll()
        self.assertEqual(live.seen, ["one", "two", "three"])

    def test_starts_where_it_is_told(self):
        self.write("old\n")
        live = Lines(self.path, offset=os.path.getsize(self.path))
        self.write("new\n", "a")
        live.poll()
        self.assertEqual(live.seen, ["new"])

    def test_new_file_bigger_than_the_old_one(self):
        self.write("[05:00] old run\n" * 5)
        live = Lines(self.path, offset=os.path.getsize(self.path))
        self.write("[06:00] today\n" * 20)   # a new file, already past the old size
        live.poll()
        self.assertEqual(live.seen, ["[06:00] today"] * 20)


class Pictures:
    def setup_pictures(self):
        self.snaps, self.removed = [], []

    def snap(self, key):
        path = f"{key}-{len(self.snaps)}.jpg"
        self.snaps.append(path)
        return path


class OneDragonFailuresTest(Folder, Pictures):
    def test_27_nov(self):
        self.setup_pictures()
        self.write(od_log())
        watch = OneDragonFailures(self.path, self.snap, self.removed.append)
        kept = watch.close()
        self.assertEqual([key for key, _ in kept], ["活跃度奖励"])
        # 每日签到 and 咖啡店 waited for a teleport ([ERROR] lines) and got past it
        self.assertEqual(self.removed, ["每日签到-0.jpg", "咖啡店-1.jpg"])

    def test_picture_from_the_error_is_kept_when_the_app_fails(self):
        self.setup_pictures()
        self.write(
            "[05:00:00.000] [operation.py 451] [INFO]: 指令[ 执行应用组 one_dragon ] 节点 执行应用 -> 执行应用 返回状态 下一个\n"
            "[05:00:01.000] [operation.py 451] [INFO]: 指令[ 咖啡店 ] 节点 检测游戏窗口 返回状态 Success\n"
            "[05:00:02.000] [operation.py 702] [ERROR]: 指令[ Wait for World Screen ] 执行失败 返回状态 未到达大世界\n"
            "[05:00:09.000] [operation.py 702] [ERROR]: 指令[ 咖啡店 ] 执行失败 返回状态 失败\n")
        watch = OneDragonFailures(self.path, self.snap, self.removed.append)
        self.assertEqual(watch.close(), [("咖啡店", "咖啡店-0.jpg")])
        self.assertEqual(len(self.snaps), 1)


class MaaFailuresTest(Folder, Pictures):
    def test_task_error_in_each_language(self):
        self.setup_pictures()
        self.write("[2026-11-27 05:10:00][INF] 开始任务: 刷理智\n"
                   "[2026-11-27 05:12:00][ERR] 任务出错: 刷理智\n"
                   "[2026-11-27 05:12:01][INF] 开始任务: 自动公招\n"
                   "[2026-11-27 05:20:00][ERR] Task error: Auto Recruit\n"
                   "[2026-11-27 05:20:00][ERR] Task error: Auto Recruit\n")
        watch = MaaFailures(self.path, self.snap, self.removed.append)
        self.assertEqual([key for key, _ in watch.close()], ["刷理智", "Auto Recruit"])


def bgi(level, message, second=0):
    """One BetterGI log entry: the header line, then the message."""
    return (f"[22:00:{second:02d}.000] [{level}] [Primary:S1:P1:T1] BetterGenshinImpact.Core.Script.Dependence.Log\n"
            f"{message}\n\n")


class BetterGIFailuresTest(Folder, Pictures):
    def watch(self, *entries):
        self.setup_pictures()
        self.write("".join(entries))
        return BetterGIFailures(self.path, self.snap, self.removed.append).close()

    def test_27_nov_run(self):
        # everything done: nothing to show
        self.setup_pictures()
        watch = BetterGIFailures(str(LOGS / "bettergi_2026-11-27.log"), self.snap, self.removed.append)
        self.assertEqual((watch.close(), self.snaps), ([], []))

    def test_commission_that_fails_both_attempts(self):
        kept = self.watch(
            bgi("INF", "执行委托：圆滚滚的易爆品 | 蒙德/果酒湖 | Basic | 第 1/2 次"),
            bgi("ERR", '["processor:自动战斗"] "执行 自动战斗 步骤" 失败: "战斗过程检测到游泳，前往七天神像重试"'),
            bgi("WRN", '委托 "圆滚滚的易爆品" 执行失败（第 1/2 次）'),
            bgi("INF", "执行委托：圆滚滚的易爆品 | 蒙德/果酒湖 | Basic | 第 2/2 次"),
            bgi("WRN", '委托 "圆滚滚的易爆品" 执行失败（第 2/2 次）'))
        # one picture, from the first sign of trouble
        self.assertEqual(kept, [("圆滚滚的易爆品", "圆滚滚的易爆品-0.jpg")])
        self.assertEqual(len(self.snaps), 1)

    def test_commission_that_gets_there_on_the_second_try(self):
        kept = self.watch(
            bgi("INF", "执行委托：临危受命 | 蒙德/奔狼领 | Basic | 第 1/2 次"),
            bgi("WRN", "检测到复苏界面，存在角色被击败，前往七天神像复活"),
            bgi("WRN", '委托 "临危受命" 执行失败（第 1/2 次）'),
            bgi("INF", "执行委托：临危受命 | 蒙德/奔狼领 | Basic | 第 2/2 次"),
            bgi("INF", "委托执行成功：临危受命"))
        self.assertEqual(kept, [])
        self.assertEqual(self.removed, ["临危受命-0.jpg"])

    def test_party_falls_in_a_domain_but_the_resin_gets_used(self):
        kept = self.watch(
            bgi("INF", "自动秘境任务：执行"),
            bgi("WRN", "检测到复苏界面，存在角色被击败，前往七天神像复活"),
            bgi("INF", '"自动秘境"：使用 "原粹树脂", 数量：20'),
            bgi("INF", "体力耗尽或者设置轮次已达标，结束自动秘境"),
            bgi("INF", '→ "任务结束"'))
        self.assertEqual(kept, [])
        self.assertEqual(self.removed, ["domain-0.jpg"])

    def test_domain_that_ends_with_resin_left(self):
        kept = self.watch(
            bgi("INF", "自动秘境任务：执行"),
            bgi("ERR", "自动秘境：未找到对应的秘境椛染之庭的传送点"),
            bgi("INF", '→ "任务结束"'),
            bgi("ERR", "前往冒险家协会领取奖励执行异常：timeout"))   # the next task's own error
        self.assertEqual(kept, [("domain", "domain-0.jpg")])

    def test_domain_cancelled_by_hand(self):
        self.setup_pictures()
        watch = BetterGIFailures(str(LOGS / "bettergi_2026-11-27_domain.log"), self.snap, self.removed.append)
        self.assertEqual([key for key, _ in watch.close()], ["domain"])

    def test_commission_reward_not_claimed(self):
        kept = self.watch(bgi("WRN", '检查每日奖励结果："未领取"，请手动检查！'))
        self.assertEqual(kept, [("daily_reward", "daily_reward-0.jpg")])


class FocusWatchTest(Folder):
    PAUSE = "当前获取焦点的窗口为: Telegram，不是原神，暂停"

    def watch(self, idle):
        self.write("")
        self.now, self.brought = [0.0], []
        return FocusWatch(self.path, 0, lambda: self.brought.append(self.now[0]),
                          idle=lambda: idle, clock=lambda: self.now[0])

    def pause_for(self, watch, seconds):
        for _ in range(seconds // 3):
            self.write(bgi("WRN", self.PAUSE), "a")
            self.now[0] += 3
            watch.check()

    def test_nobody_at_the_pc(self):
        # at 4 in the morning a pop-up took the focus: bring the game back, every 10 s at most
        watch = self.watch(idle=3600)
        self.pause_for(watch, 30)
        self.assertEqual(self.brought, [3.0, 15.0, 27.0])

    def test_someone_using_the_pc(self):
        watch = self.watch(idle=5)
        self.pause_for(watch, 30)
        self.assertEqual(self.brought, [])

    def test_not_paused(self):
        watch = self.watch(idle=3600)
        self.write(bgi("INF", "自动秘境：点击 \"单人挑战\""), "a")
        watch.check()
        self.assertEqual(self.brought, [])


if __name__ == "__main__":
    unittest.main()
