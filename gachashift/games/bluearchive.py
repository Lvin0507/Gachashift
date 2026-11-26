"""Blue Archive JP (PC client) via BAAS.

The JP client must be opened from its launcher (click スタート), BAAS needs a 1280x720 window,
and BAAS exits by itself when done. Its .exe is only a launcher that starts the real BAAS
(pythonw.exe inside the BAAS folder), so we watch every process living in that folder."""

import os
import subprocess
import time

from .. import report as R
from ..system import StopRequested, kill, kill_processes, launch_and_click, pause, processes_in, ts
from .base import Game, minutes_since

REG_KEY = r"Software\YostarJP\BlueArchive"
GAME_EXE = "BlueArchive.exe"
# Unity stores screen settings as "<name>_h<hash>"; match on the prefix
WINDOWED = {
    "Screenmanager Fullscreen mode": 3,
    "Screenmanager Resolution Width": 1280,
    "Screenmanager Resolution Height": 720,
    "Screenmanager Resolution Window Width": 1280,
    "Screenmanager Resolution Window Height": 720,
    "Screenmanager Resolution Use Native": 0,
    "Screenmanager Window Position X": 0,
    "Screenmanager Window Position Y": 0,
}


def set_windowed():
    """Write the 1280x720 window BAAS needs. Full screen isn't restored: the game keeps its
    own full-screen toggle elsewhere, so the player just presses Alt+Enter."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0,
                        winreg.KEY_READ | winreg.KEY_WRITE) as key:
        i = 0
        while True:
            try:
                name = winreg.EnumValue(key, i)[0]
            except OSError:
                break
            for prefix, value in WINDOWED.items():
                if name.startswith(prefix + "_h"):
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
            i += 1


class BlueArchive(Game):
    id = "bluearchive"
    reset = (9, 4)  # 04:00 JST
    required = ("baas_dir", "launcher_path")

    def game_exes(self):
        return (GAME_EXE,)

    def launcher_exes(self):
        return (os.path.basename(self.cfg.get("launcher_path") or ""),)

    def open_launcher(self):
        launcher = self.cfg.get("launcher_path")
        if not launcher:
            return None
        return lambda: subprocess.Popen([launcher], cwd=os.path.dirname(launcher),
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def run(self, start_timeout=300, timeout=3600):
        baas_dir = self.cfg["baas_dir"]
        baas_exe = self.cfg.get("baas_exe") or os.path.join(baas_dir, "BlueArchiveAutoScript.exe")
        launcher = self.cfg["launcher_path"]
        launcher_exe = os.path.basename(launcher)
        rep = self.new_report()
        try:
            set_windowed()
        except OSError as e:
            print(f"could not set window size: {e}")
        reason, saw_baas = "timeout", False
        start = time.time()
        try:
            ok = launch_and_click(self.open_launcher(), launcher_exe, self.cfg["start_button"],
                                  GAME_EXE, remember=self.launcher_key(),
                                  careful=self.clicks_carefully())
            if not ok:
                rep.add("baas", R.FAIL)
                rep.note("note.not_started", hint="hint.launcher")
                return rep
            start = time.time()  # time BAAS itself, not the launcher
            print(f"[{ts()}] starting {baas_exe}")
            # its own console: redirecting its output crashes it on a cp932 system
            subprocess.Popen([baas_exe], cwd=baas_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
            watch = self.watch()  # BAAS keeps no log, so only the screen tells
            while time.time() - start < timeout:
                # look often at first: with nothing due, BAAS can come and go in seconds
                pause(2 if time.time() - start < 60 else 15)
                if saw_baas and self.stuck(watch):
                    reason = "stalled"
                    break
                procs = processes_in(baas_dir)
                baas_running = any((p.info.get("name") or "").lower() == "pythonw.exe" for p in procs)
                if baas_running:
                    saw_baas = True
                elif saw_baas:
                    # BAAS itself has exited; helpers it leaves behind (e.g. adb.exe)
                    # are closed in the finally block below
                    reason = "exited"
                    break
                if not procs:
                    # nothing of BAAS left: it either ran and exited, or closed before its
                    # tasks started (BAAS itself was started; it just didn't stay)
                    reason = "exited" if saw_baas else "closed_early"
                    break
                if not saw_baas and time.time() - start > start_timeout:
                    reason = "not_started"
                    break
        except StopRequested as stop:
            # BAAS keeps no task log, so all we can say is that it didn't finish
            rep.add("baas", R.SKIPPED)
            stop.report = rep
            raise
        finally:
            self.capture([GAME_EXE, launcher_exe], baas_dir)
            kill_processes(processes_in(baas_dir))
            kill([GAME_EXE, launcher_exe])
            time.sleep(3)

        minutes = minutes_since(start)
        if reason == "exited" and minutes >= 3:
            rep.add("baas", R.OK)
            rep.note("note.finished", minutes=minutes)
        elif reason == "exited":
            rep.add("baas", R.WARN)
            rep.note("note.quick_exit", minutes=minutes)
        elif reason == "closed_early":
            rep.add("baas", R.WARN)
            rep.note("note.baas_closed_early", seconds=max(1, round(time.time() - start)))
        elif reason == "not_started":
            rep.add("baas", R.FAIL)
            rep.note("note.baas_not_started")
        else:
            rep.add("baas", R.WARN)
            rep.note("note.timeout", minutes=minutes)
        return rep
