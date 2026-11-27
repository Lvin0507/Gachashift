"""A whole Genshin run: BetterGI writes its log while it runs, then exits; the report and the
pictures taken on the way."""

import datetime
import os
import tempfile
import unittest
from unittest import mock

from gachashift import report as R
from gachashift.games import genshin
from gachashift.games.base import Game


def entry(level, message):
    return f"[22:00:00.000] [{level}] [Primary:S1:P1:T1] BetterGenshinImpact.Core.Script.Dependence.Log\n{message}\n\n"


# what BetterGI writes, by the second it is written at
SCRIPT = [
    (6, entry("INF", "委托 1 | 圆滚滚的易爆品 | 未完成 | Basic | 蒙德 | 果酒湖 | 坐标: (-544, 2611)")),
    (6, entry("INF", "委托 2 | 临危受命 | 已完成 | Basic | - | - | 坐标: -")),
    (6, entry("INF", "委托 3 | 冰凉凉的大团危机 | 已完成 | Basic | - | - | 坐标: -")),
    (6, entry("INF", "委托 4 | 鸽子习惯一去不回 | 已完成 | NPC | - | - | 坐标: -")),
    (9, entry("INF", "执行委托：圆滚滚的易爆品 | 蒙德/果酒湖 | Basic | 第 1/2 次")),
    (30, entry("ERR", '["processor:自动战斗"] "执行 自动战斗 步骤" 失败: "战斗过程检测到游泳，前往七天神像重试"')),
    (60, entry("WRN", '委托 "圆滚滚的易爆品" 执行失败（第 1/2 次）')),
    (63, entry("INF", "执行委托：圆滚滚的易爆品 | 蒙德/果酒湖 | Basic | 第 2/2 次")),
    (120, entry("WRN", '委托 "圆滚滚的易爆品" 执行失败（第 2/2 次）')),
    (150, entry("INF", '检查每日奖励结果："今日奖励已领取"')),
    (153, entry("INF", "一条龙和配置组任务结束")),
]
EXIT_AT = 160


class GenshinRunTest(unittest.TestCase):
    def play(self, script=SCRIPT, exit_at=EXIT_AT):
        """Runs Genshin with BetterGI writing `script`; returns (report, game, pictures)."""
        with tempfile.TemporaryDirectory() as folder:
            log = genshin.log_path(folder, datetime.date.today())
            os.makedirs(os.path.dirname(log))
            with open(log, "w", encoding="utf-8") as f:
                f.write(entry("INF", "an earlier run today"))
            # date.today() follows the patched clock, so start it now, not in 1970
            base = genshin.time.time()
            clock, written = [base], [0]

            def pause(seconds):
                clock[0] += seconds
                with open(log, "a", encoding="utf-8") as f:
                    while written[0] < len(script) and script[written[0]][0] <= clock[0] - base:
                        f.write(script[written[0]][1])
                        written[0] += 1

            snaps = []
            game = genshin.Genshin({"bgi_path": os.path.join(folder, "BetterGI.exe")})
            game.shot_dir = folder
            with mock.patch.multiple(genshin, kill=lambda names: None, pause=pause,
                                     process_running=lambda name: clock[0] - base < exit_at), \
                    mock.patch.object(genshin.subprocess, "Popen", lambda *a, **k: None), \
                    mock.patch.object(genshin.time, "time", lambda: clock[0]), \
                    mock.patch.object(genshin.time, "sleep", lambda s: None), \
                    mock.patch.object(Game, "capture", lambda self, *a: None), \
                    mock.patch.object(Game, "stuck", lambda self, watch: False), \
                    mock.patch.object(Game, "snap", lambda self, key: snaps.append(key) or f"{key}.jpg"):
                rep = game.run()
        return rep, game, snaps

    def test_failed_commission_gets_its_picture(self):
        rep, game, snaps = self.play()
        self.assertEqual({t.key: (t.status, t.detail) for t in rep.tasks}, rep.notes and
                         {"commissions": (R.PARTIAL, "3/4"), "daily_reward": (R.OK, "")} if False else
                         {"commissions": (R.PARTIAL, "3/4"), "daily_reward": (R.OK, "")})
        self.assertEqual(game.failure_shots, [("圆滚滚的易爆品", "圆滚滚的易爆品.jpg")])
        self.assertEqual(snaps, ["圆滚滚的易爆品"])   # one picture, at the first sign of trouble

    def test_bettergi_left_open(self):
        # 27 Nov: a new one-dragon config ("resin") had no finishing action, so BetterGI stayed
        # open after its end line; Gachashift closed it a minute later and said nothing
        rep, game, _ = self.play(exit_at=10 ** 6)
        self.assertIn("tool.bgi_finish", [key for key, _ in rep.notes])
        self.assertEqual(R.outcome(rep), "warn")
        self.assertIn("它的工具有个设定要改", R.actions(rep, "zh")[0])

    def test_tool_note_not_repeated(self):
        from gachashift import runner
        rep = R.GameReport("genshin")
        rep.add("domain", R.OK, "×8")
        rep.note("tool.bgi_finish", config="resin")
        with mock.patch.object(runner.toolcheck, "check_game", lambda gid, cfg: ["tool.bgi_finish"]):
            runner.explain(rep, {})
        self.assertEqual([key for key, _ in rep.notes], ["tool.bgi_finish"])


if __name__ == "__main__":
    unittest.main()
