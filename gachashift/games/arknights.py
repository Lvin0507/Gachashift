"""Arknights via MAA (PC client). MAA starts the game but never exits on its own, so we
watch its log for the completion message and then close it."""

import os
import re
import subprocess
import time

from .. import report as R
from ..system import (StopRequested, gryphlink_processes, kill, kill_processes, log_size, pause,
                      process_running, read_since, ts)
from .base import Game

# MAA writes gui.log in its UI language. Each list holds the text in zh-CN, zh-TW, en-US,
# ja-JP and ko-KR, from MAA's Res/Localizations (tools/check_upstream.py watches them).
DONE_MARKERS = ["任务已全部完成", "任務已全部完成", "All task(s) completed", "すべてのタスクが完了しました",
                "모든 작업을 완료했습니다"]
START_WORDS = ["开始任务:", "開始任務:", "Start task:", "タスク開始:", "작업 시작:"]
COMPLETE_WORDS = ["完成任务:", "完成任務:", "Complete task:", "タスク完了:", "작업 완료:"]
RECRUIT_CONFIRM = ["已确认招募", "已確認招募", "Recruit confirm", "募集を行いました", "모집 확정"]
RECRUIT_TASK = ["自动公招", "自動公招", "Auto Recruit", "公開求人", "공개모집"]


def _names(words, text):
    """Task names after any of the words, to the end of the line: a name can have spaces."""
    pattern = r"(?:%s)[ \u00a0]*(.+?)[ \t]*$" % "|".join(map(re.escape, words))
    return [name.split("\\n")[0].strip() for name in re.findall(pattern, text, re.M)]


def parse_maa_log(text, reason, rep):
    started = _names(START_WORDS, text)
    finished = set(_names(COMPLETE_WORDS, text))
    recruits = sum(text.count(word) for word in RECRUIT_CONFIRM)
    if not started:
        rep.note("note.no_records")
    for name in dict.fromkeys(started):  # keep order, drop repeats
        detail = f"x{recruits}" if name in RECRUIT_TASK and name in finished else ""
        # a task cut short by a stop didn't fail; it just didn't get to finish
        unfinished = R.SKIPPED if reason == "stopped" else R.FAIL
        rep.add(name, R.OK if name in finished else unfinished, detail)
    if reason not in ("done", "stopped"):
        rep.note("note.no_done_marker", reason=reason)
    return rep


class Arknights(Game):
    id = "arknights"
    required = ("maa_path", "maa_log")

    def game_exes(self):
        return (self.cfg.get("game_exe") or "Arknights.exe",)

    def launcher_running(self):
        return bool(gryphlink_processes())

    def launcher_key(self):
        return "arknights:gryphlink"

    def launcher_group(self):
        return "gryphlink"

    def launcher_screen(self):
        from ..updater import WindowsScreen
        return WindowsScreen(processes=gryphlink_processes, game_exes=self.game_exes())

    def run(self, timeout=1800):
        path, log = self.cfg["maa_path"], self.cfg["maa_log"]
        offset = log_size(log)
        reason, missing, stop = "timeout", 0, None
        try:
            print(f"[{ts()}] starting {path}")
            subprocess.Popen([path], cwd=os.path.dirname(path))
            start = time.time()
            watch = self.watch(log)
            while time.time() - start < timeout:
                pause(15)
                if self.stuck(watch):
                    reason = "stalled"
                    break
                if any(m in read_since(log, offset) for m in DONE_MARKERS):
                    reason = "done"
                    break
                # MAA disappears briefly while self-updating, so require two misses in a row
                missing = 0 if process_running("MAA.exe") else missing + 1
                if missing >= 2:
                    reason = "exited"
                    break
            pause(10)  # let MAA finish writing its log
        except StopRequested as e:
            stop, reason = e, "stopped"
        finally:
            # the Arknights PC client can bring up GRYPHLINK too
            leftovers = ["MAA.exe", self.cfg.get("game_exe") or "Arknights.exe"]
            self.capture(leftovers)
            kill(leftovers)
            kill_processes(gryphlink_processes())
            time.sleep(3)
        rep = parse_maa_log(read_since(log, offset), reason, self.new_report())
        if stop:
            stop.report = rep
            raise stop
        return rep
