"""Wuthering Waves via ok-ww (-t GardenTask -e).

ok-ww exits by itself after a successful run but stays open after a task exception, so we also
watch its log for the end of the task and always close it ourselves. The Steam build opens
Kuro's launcher (launcher_main.exe), which needs a click on its start button, so we open the
game through Steam with admin rights, click the button, and hand the running game to ok-ww."""

import os
import re
import subprocess
import time

from .. import report as R
from ..system import (StopRequested, kill, kill_processes, launch_and_click, log_size, pause,
                      processes_in, read_since, restart_steam_if_running, ts)
from .base import Game

GAME_EXE = "Client-Win64-Shipping.exe"
# ok-ww writes its log in its UI language: zh-CN, zh-TW, English, Japanese, Korean, Spanish,
# from ok-ww's i18n folder (tools/check_upstream.py watches them)
DONE = ["乐园任务完成", "樂園任務完成", "Garden task completed", "楽園タスク完了", "낙원 임무 완료",
        "Tarea del jardín completada"]
CURRENT = ["当前乐园进度：", "當前樂園進度：", "Garden current: ", "現在の楽園進捗: ", "현재 낙원 진행도: ",
           "Progreso actual del jardín: "]
FAILED = "exception stopped"  # from ok-script, not translated
# progress appears as "当前乐园进度：[6000_1.00]" when full (older ok-ww: "本周游历值_1.00, 4400/6000")
PROGRESS = re.compile(r"本周游历值_[\d.]+, (\d+/\d+|已达到上限)|(?:%s)\[(\d+)_"
                      % "|".join(map(re.escape, CURRENT)))
EXCEPTION = re.compile(r"^Exception: (.+)$", re.M)


def ended(text):
    return any(word in text for word in DONE) or FAILED in text


def parse_ww_log(text, rep):
    """Decide from ok-ww's own completion and failure lines, not loose keywords."""
    if not text.strip():
        rep.add("garden", R.WARN)
        rep.note("note.no_records")
        return rep
    progress = PROGRESS.findall(text)
    detail = next((a or b for a, b in reversed(progress) if a or b), "")
    if detail in ("已达到上限", "6000"):
        detail = "max"
    if any(word in text for word in DONE):
        rep.add("garden", R.OK, detail)
    elif FAILED in text:
        reasons = EXCEPTION.findall(text)
        rep.add("garden", R.FAIL, reasons[-1].strip() if reasons else "")
    elif "game exited" in text:
        rep.add("garden", R.FAIL, "game closed")
    else:
        rep.add("garden", R.WARN, detail)
    return rep


class WutheringWaves(Game):
    id = "wuthering"
    required = ("okww_path", "log_path")

    def game_exes(self):
        return (GAME_EXE,)

    def launcher_exes(self):
        return (self.cfg.get("launcher_exe") or "launcher_main.exe",)

    def steam_app(self):
        if not self.cfg.get("steam_client"):
            return None
        return self.cfg.get("steam_appid") or "3513350", self.cfg.get("game_path") or ""

    def open_launcher(self):
        if not self.cfg.get("steam_client"):
            return None
        appid = self.cfg.get("steam_appid") or "3513350"

        def open_it():
            restart_steam_if_running()  # so the game inherits our admin rights
            os.startfile(f"steam://rungameid/{appid}")
        return open_it

    def _open_through_steam(self):
        return launch_and_click(
            self.open_launcher(), self.cfg.get("launcher_exe") or "launcher_main.exe",
            self.cfg["start_button"], GAME_EXE, wait_after=60, remember=self.launcher_key(),
            careful=self.clicks_carefully())

    def run(self, timeout=5400):
        path, log = self.cfg["okww_path"], self.cfg["log_path"]
        folder = os.path.dirname(path)
        offset = log_size(log)
        start, stop = time.time(), None
        try:
            if self.cfg.get("steam_client") and not self._open_through_steam():
                rep = self.new_report()
                rep.add("garden", R.FAIL)
                rep.note("note.not_started", hint="hint.steam")
                return rep
            print(f"[{ts()}] starting {path}")
            subprocess.Popen([path, "-t", self.cfg.get("task") or "GardenTask", "-e"], cwd=folder)
            pause(15)
            ended_at, watch = None, self.watch(log)
            while processes_in(folder) and time.time() - start < timeout:
                pause(10)
                if self.stuck(watch):
                    break
                text = read_since(log, offset)
                if ended_at is None and ended(text):
                    ended_at = time.time()
                # give ok-ww a minute to exit on its own after the task ends, then close it
                if ended_at and time.time() - ended_at > 60:
                    break
        except StopRequested as e:
            stop = e
        finally:
            # ok-ww stays open after a failure; never leave it running for the next game
            leftovers = [GAME_EXE, self.cfg.get("launcher_exe") if self.cfg.get("steam_client") else None]
            self.capture(leftovers, folder)
            kill_processes(processes_in(folder))
            kill(leftovers)
            time.sleep(5)
        text = read_since(log, offset)
        rep = parse_ww_log(text, self.new_report())
        if stop:
            if not ended(text):
                rep = self.new_report()
                rep.add("garden", R.SKIPPED)
            stop.report = rep
            raise stop
        return rep
