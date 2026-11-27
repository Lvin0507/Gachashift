"""Zenless Zone Zero via OneDragon.

Official client: OneDragon opens the game itself (`-o -c`), which is its documented way.
Steam client: the game refuses to start unless Steam launches it, and Steam opens the
HoYoverse launcher (HYP.exe) that needs a click, so we open the game first and then hand
the running game to OneDragon. Either way OneDragon exits by itself when done."""

import os
import re
import subprocess
import time

from .. import report as R
from ..system import (StopRequested, kill, kill_processes, launch_and_click, log_size, pause,
                      process_running, processes_in, read_since, restart_steam_if_running, ts)
from .base import FailureShots, Game, minutes_since, remove_file

GAME_EXE = "ZenlessZoneZero.exe"
SERVER_UTC = {"asia": 8, "america": -5, "europe": 1}
LINE = re.compile(r"指令\[ (.+?) \] (?:节点 .*?返回状态 (.*)|执行成功 返回状态 (.*)|执行失败 返回状态 (.*))$")


class OneDragonFailures(FailureShots):
    """OneDragon's log.txt while it runs. Apps are found the way parse_od_log finds them.
    A sub-step's [ERROR] (a teleport that hasn't arrived yet) takes a picture that is kept
    only if the app then fails: by the time OneDragon logs the app's failure it has usually
    gone back to the world map."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.expect_app = False

    def line(self, raw):
        m = LINE.search(raw)
        if not m:
            if "[ERROR]" in raw:
                self.error()
            return
        name, node, ok, fail = m.groups()
        if name.startswith("执行应用组"):
            self.expect_app = True
            return
        if name == "一条龙":
            return
        current = self.current[1] if self.current else None
        if self.expect_app and node is not None:
            self.expect_app = False
            self.begin(name, name)
        elif name == current and ok is not None:
            self.succeeded(name)
        elif name == current and fail is not None:
            self.failed(name, name)
        elif fail is not None:
            self.error()  # a sub-step failed; the app may still get past it


def parse_od_log(text, rep, minutes, stopped=False):
    """OneDragon logs every operation as 指令[ name ]. The apps of the one-dragon group start
    right after a line from 指令[ 执行应用组 ... ]; anything inside an app (Return to World,
    Teleport, ...) is a sub-step and is ignored. Disabled apps are not reported."""
    results, expect_app, current, overall = {}, False, None, None
    for line in text.splitlines():
        m = LINE.search(line.strip())
        if not m:
            continue
        name, node, ok, fail = m.groups()
        if name.startswith("执行应用组"):
            expect_app = True
            if node and node.startswith("应用已完成 "):
                results[node.split(" ", 1)[1]] = (R.ALREADY, "")
            continue
        if name == "一条龙":
            overall = ("ok", ok) if ok is not None else (("fail", fail) if fail is not None else overall)
            continue
        if expect_app and node is not None:
            current, expect_app = name, False
            results.setdefault(current, (R.WARN, ""))
        elif name == current and ok is not None:
            results[current] = (R.OK, "")
        elif name == current and fail is not None:
            results[current] = (R.FAIL, fail)

    if not results and overall is None:
        rep.note("note.no_records")
        return rep
    for app, (status, detail) in results.items():
        if stopped and status == R.WARN:
            status = R.SKIPPED  # the app that was running when the user stopped
        rep.add(app, status, detail)
    if stopped:
        return rep
    if overall and overall[0] == "ok":
        rep.note("note.finished", minutes=minutes)
    elif overall:
        rep.note("note.interrupted", reason=overall[1])
    else:
        rep.note("note.no_done_marker", reason="no end record")
    return rep


class ZenlessZoneZero(Game):
    id = "zzz"
    required = ("od_dir",)

    @property
    def reset(self):
        return (SERVER_UTC.get(self.cfg.get("server"), 8), 4)

    def game_exes(self):
        return (GAME_EXE,)

    def launcher_exes(self):
        return (self.cfg.get("launcher_exe"),) if self.cfg.get("client") == "steam" else ()

    def steam_app(self):
        if self.cfg.get("client") != "steam":
            return None
        return self.cfg.get("steam_appid") or None, self.cfg.get("game_path") or ""

    def open_launcher(self):
        if self.cfg.get("client") != "steam":
            return None
        appid = self.cfg.get("steam_appid")

        def open_it():
            restart_steam_if_running()
            os.startfile(f"steam://rungameid/{appid}")
        return open_it

    def _open_through_steam(self):
        return launch_and_click(
            self.open_launcher(), self.cfg["launcher_exe"], self.cfg["start_button"], GAME_EXE,
            wait_after=60, remember=self.launcher_key(), careful=self.clicks_carefully())

    def run(self, timeout=3600):
        od_dir = self.cfg["od_dir"]
        # The runtime launcher (in some OneDragon builds) starts without pulling code or
        # reinstalling packages, so an unattended run can't stop at an update prompt
        runtime = os.path.join(od_dir, "OneDragon-RuntimeLauncher.exe")
        od_exe = runtime if os.path.exists(runtime) else os.path.join(od_dir, "OneDragon-Launcher.exe")
        log = os.path.join(od_dir, ".log", "log.txt")
        steam = self.cfg.get("client") == "steam"
        offset = log_size(log)
        rep = self.new_report()
        start, reason, saw_od, saw_game, game_gone = time.time(), "timeout", False, False, 0
        stop = failures = None
        try:
            if steam:
                if not self._open_through_steam():
                    rep.add("一条龙", R.FAIL)
                    rep.note("note.not_started", hint="hint.steam")
                    return rep
                saw_game = True
            print(f"[{ts()}] starting {od_exe} -o -c")
            subprocess.Popen([od_exe, "-o", "-c"], cwd=od_dir,
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
            watch = self.watch(log)
            failures = OneDragonFailures(log, self.snap, remove_file, offset) if self.shot_dir else None
            rounds = 0
            while time.time() - start < timeout:
                # every 3 s for the failure pictures; the rest every 15 s as before
                pause(3)
                rounds += 1
                if failures:
                    failures.poll()
                if rounds % 5:
                    continue
                if self.stuck(watch):
                    reason = "stalled"
                    break
                procs = processes_in(od_dir)
                saw_od = saw_od or bool(procs)
                if process_running(GAME_EXE):
                    saw_game, game_gone = True, 0
                elif saw_game:
                    game_gone += 1
                if saw_od and not procs:
                    reason = "exited"
                    break
                if game_gone >= 2:  # -c closes the game at the end
                    reason = "game_closed"
                    break
        except StopRequested as e:
            stop, reason = e, "stopped"
        finally:
            if failures:
                self.failure_shots = failures.close()
            leftovers = [GAME_EXE, self.cfg.get("launcher_exe") if steam else None]
            self.capture(leftovers, od_dir)
            kill_processes(processes_in(od_dir))
            kill(leftovers)
            time.sleep(3)
        print(f"[{ts()}] ZZZ ended: {reason}, OneDragon seen={saw_od}, game seen={saw_game}")
        rep = parse_od_log(read_since(log, offset), rep, minutes_since(start), stopped=bool(stop))
        if stop:
            stop.report = rep
            raise stop
        finished = any(key == "note.finished" for key, _ in rep.notes)
        if not rep.tasks and finished:
            rep.note("note.no_task_lines")  # the run ended well, but no app lines were read
        elif not rep.tasks:
            rep.note("note.no_done_marker", reason=f"{reason}, OneDragon seen={saw_od}")
        return rep
