"""Windows helpers shared by every game: processes, logs, windows, real-mouse clicks,
and the quiet mode (mute + dim) used while a run is in progress."""

import ctypes
import datetime
import os
import subprocess
import time
from ctypes import wintypes

import psutil

from .config import app_dir


def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")


# ---------- stopping a run ----------
class StopRequested(Exception):
    """Raised inside a run when the user asked Gachashift to stop."""


def stop_file():
    """Creating this file (from the App or the Stop shortcut) asks a running Gachashift to stop."""
    return app_dir() / "stop.request"


def stop_requested():
    return stop_file().exists()


def clear_stop():
    try:
        stop_file().unlink()
    except FileNotFoundError:
        pass


_PUMP = None  # called about once a second while a run waits (the tray icon's events)


def set_pump(pump):
    global _PUMP
    _PUMP = pump


def pause(seconds):
    """Sleep, but give up at once with StopRequested if the user asked to stop. Every wait in a
    run goes through here, so a stop takes effect within a second wherever the run is."""
    end = time.time() + seconds
    while True:
        if _PUMP is not None:
            try:
                _PUMP()
            except Exception:
                pass
        if stop_requested():
            raise StopRequested()
        left = end - time.time()
        if left <= 0:
            return
        time.sleep(min(1.0, left))


def seconds_since_input():
    """How long ago the keyboard or mouse was last used in this session."""
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000


# ---------- processes ----------
def process_running(exe_name):
    """Exact name check via psutil (tasklist truncates long names)."""
    exe_name = exe_name.lower()
    return any((p.info.get("name") or "").lower() == exe_name for p in psutil.process_iter(["name"]))


def kill(exe_names):
    for name in exe_names:
        if name:
            subprocess.run(["taskkill", "/F", "/IM", name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def processes_in(folder):
    """Processes whose executable lives inside `folder` (e.g. a tool's bundled python).
    Matching on the path keeps us from touching our own python.exe or anyone else's."""
    root = os.path.normcase(os.path.abspath(folder)) + os.sep
    found = []
    for p in psutil.process_iter(["exe", "name"]):
        exe = p.info.get("exe")
        if exe and os.path.normcase(exe).startswith(root):
            found.append(p)
    return found


# GRYPHLINK (Endfield, and the Arknights PC client) runs under plain names such as
# Launcher.exe or Games.exe, which other programs use too, so it is told apart by its folder
GRYPHLINK_FOLDERS = ("gryphlink", "hypergryph")
GRYPHLINK_NAMES = ("launcher.exe", "games.exe")


def gryphlink_processes():
    found = []
    for p in psutil.process_iter(["exe", "name"]):
        exe = (p.info.get("exe") or "").lower()
        if (p.info.get("name") or "").lower() in GRYPHLINK_NAMES and any(f in exe for f in GRYPHLINK_FOLDERS):
            found.append(p)
    return found


def kill_processes(procs):
    for p in procs:
        try:
            p.kill()
        except psutil.Error:
            pass


# ---------- screenshots ----------
_QT_APP = None  # kept alive for the whole run; Qt allows only one application object


def capture_screen(path, quality=70):
    """Save the main screen as a JPEG and return its path, or None if that wasn't possible
    (e.g. on the lock screen). Uses Qt, which the program already ships."""
    global _QT_APP
    try:
        from PySide6.QtWidgets import QApplication
        _QT_APP = QApplication.instance() or QApplication([])
        screen = _QT_APP.primaryScreen()
        if screen is None:
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if screen.grabWindow(0).save(str(path), "JPG", quality):
            return str(path)
    except Exception as e:
        print(f"[{ts()}] screenshot failed: {e}")
    return None


def fingerprint_of(image, width=64, height=36):
    """A tiny grey copy of a QImage, one byte per pixel; None when it is (nearly) all black."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    grey = image.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    grey = grey.convertToFormat(QImage.Format_Grayscale8)
    pixels = b"".join(bytes(grey.constScanLine(y))[:width] for y in range(height))
    return pixels if pixels and max(pixels) > 8 else None


def screen_fingerprint():
    """A fingerprint of the screen, for telling whether anything on it is moving; None when
    the screen can't be seen (locked, switched off: the picture comes back black)."""
    global _QT_APP
    try:
        from PySide6.QtWidgets import QApplication
        _QT_APP = QApplication.instance() or QApplication([])
        screen = _QT_APP.primaryScreen()
        if screen is None:
            return None
        return fingerprint_of(screen.grabWindow(0).toImage())
    except Exception:
        return None


def looks_different(a, b, threshold=2.0):
    """True when two fingerprints differ by more than a flicker (mean change per pixel)."""
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a)) > threshold


class StallWatch:
    """Notices a tool that has stopped making progress: its log hasn't grown and nothing on
    the screen has moved for `minutes`. A quiet log alone isn't enough (a long fight can be
    quiet), and a screen that can't be seen never counts as still."""

    def __init__(self, log=None, minutes=15, clock=time.time, look=screen_fingerprint):
        self.log, self.limit, self.clock, self.look = log, minutes * 60, clock, look
        self.minutes = minutes
        self.last_change = clock()
        self.size = self.screen = None

    def stuck(self):
        now = self.clock()
        size = log_size(self.log) if self.log else None
        log_moved, self.size = size != self.size, size
        shot = self.look()
        if shot is None:
            screen_moved = True  # can't see the screen: never call it still
        else:
            screen_moved = self.screen is None or looks_different(shot, self.screen)
            self.screen = shot
        if log_moved or screen_moved:
            self.last_change = now
        return now - self.last_change >= self.limit


# ---------- logs ----------
# The first bytes of each log at the time its size was taken. Some tools (OneDragon) start
# a new log file on every launch; once the new file grows past the old size, a size check
# alone can no longer tell, so a changed start of the file also means "read from the top".
_LOG_HEADS = {}
HEAD_BYTES = 256


def _head(path):
    try:
        with open(path, "rb") as f:
            return f.read(HEAD_BYTES)
    except OSError:
        return b""


def log_size(path):
    if not path or not os.path.exists(path):
        return 0
    _LOG_HEADS[path] = _head(path)
    return os.path.getsize(path)


def read_since(path, offset):
    """Everything written to `path` after byte `offset` (handles truncation/rotation)."""
    if not path or not os.path.exists(path):
        return ""
    old_head = _LOG_HEADS.get(path, b"")
    replaced = offset and old_head and _head(path)[:len(old_head)] != old_head
    if replaced or os.path.getsize(path) < offset:
        offset = 0
    with open(path, "rb") as f:
        f.seek(offset)
        return f.read().decode("utf-8", errors="ignore")


# ---------- windows and clicks ----------
def _user32():
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    return user32


def make_dpi_aware():
    """Use real pixel coordinates even with 125%/150% display scaling."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main_window_of(exe_name):
    """The largest visible top-level window owned by a process with this exe name, or None."""
    user32 = _user32()
    pids = {p.pid for p in psutil.process_iter(["name"])
            if (p.info.get("name") or "").lower() == exe_name.lower()}
    best, best_area = None, 0
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        nonlocal best, best_area
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids:
                rect = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                if rect.right * rect.bottom > best_area:
                    best, best_area = hwnd, rect.right * rect.bottom
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return best


def bring_to_front(hwnd):
    """Restore a window and make it the foreground window. Returns True if it is in front."""
    user32 = _user32()
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    if user32.GetForegroundWindow() != hwnd:
        # Windows sometimes refuses focus changes; minimizing and restoring usually works
        user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        time.sleep(0.3)
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)
    return user32.GetForegroundWindow() == hwnd


def move_mouse_to(hwnd, fx, fy):
    """Put the mouse at a fraction of a window's client area (to show a spot, not click it)."""
    user32 = _user32()
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    point = wintypes.POINT(int(rect.right * fx), int(rect.bottom * fy))
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    user32.SetCursorPos(point.x, point.y)


def click_in_window(hwnd, fx, fy):
    """Bring the window to the front and click with the real mouse at a fraction of its client
    area. Skips the click if the window won't come to the front, so a click never lands on
    some other window that happens to be on top. Returns True if it clicked."""
    user32 = _user32()
    if not bring_to_front(hwnd):
        print(f"[{ts()}] launcher window is not in front; not clicking this time")
        return False
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    point = wintypes.POINT(int(rect.right * fx), int(rect.bottom * fy))
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    user32.SetCursorPos(point.x, point.y)
    time.sleep(0.1)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
    return True


def launch_and_click(open_launcher, launcher_exe, button, game_exe, wait_after=30, timeout=600,
                     look_after=3, find=None):
    """Open a game launcher, then keep clicking its start button until the game process appears.
    Clicking repeats because the launcher may still be checking for updates at first.
    With no calibrated position, or after look_after clicks there did nothing (a new screen,
    a redesigned launcher), the button is looked for in the window instead."""
    from . import buttonfind
    find = find or buttonfind.find_in_window
    make_dpi_aware()
    open_launcher()
    start = time.time()
    position = tuple(button) if button else None
    clicks, looked = 0, False
    while time.time() - start < timeout:
        pause(10)
        if process_running(game_exe):
            print(f"[{ts()}] game started, waiting for it to load...")
            pause(wait_after)
            return True
        hwnd = main_window_of(launcher_exe)
        if not hwnd:
            continue
        if position is None or (clicks >= look_after and not looked):
            looked = position is not None  # with nothing calibrated, keep looking until found
            found = find(hwnd) if bring_to_front(hwnd) else None
            if found and (position is None or buttonfind.far_apart(found, position)):
                print(f"[{ts()}] found the start button at {found[0]}, {found[1]}; clicking there now")
                position = found
            if position is None:
                continue
        print(f"[{ts()}] clicking the start button in {launcher_exe}")
        if click_in_window(hwnd, *position):
            clicks += 1
    return False


def wait_for_reset(utc_offset_hours, reset_hour=4, margin_minutes=5, max_wait_hours=2, on_wait=None):
    """Wait until just after a server's daily reset (if it is due within max_wait_hours),
    so the run counts for today rather than yesterday. Returns the minutes waited."""
    tz = datetime.timezone(datetime.timedelta(hours=utc_offset_hours))
    now = datetime.datetime.now(tz)
    reset = now.replace(hour=reset_hour, minute=margin_minutes, second=0, microsecond=0)
    wait = (reset - now).total_seconds()
    if 0 < wait <= max_wait_hours * 3600:
        if on_wait:
            on_wait(round(wait / 60))
        pause(wait)
        return round(wait / 60)
    return 0


# ---------- screen gamma ----------
class _DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]


_RAMP = wintypes.WORD * 768  # 256 steps each for red, green and blue


def gamma_marker():
    """Present while the screens are darkened, so a run that died can be cleaned up later."""
    return app_dir() / "gamma.dim"


def _displays():
    names, i = [], 0
    while True:
        device = _DISPLAY_DEVICE()
        device.cb = ctypes.sizeof(device)
        if not ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(device), 0):
            return names
        if device.StateFlags & 1:  # attached to the desktop
            names.append(device.DeviceName)
        i += 1


def _set_ramp(name, ramp):
    gdi32 = ctypes.windll.gdi32
    hdc = gdi32.CreateDCW("DISPLAY", name, None, None)
    try:
        return bool(gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp)))
    finally:
        gdi32.DeleteDC(hdc)


def _linear_ramp(level):
    ramp = _RAMP()
    for channel in range(3):
        for i in range(256):
            ramp[channel * 256 + i] = min(65535, int(i * 257 * level))
    return ramp


def dim_gamma(level=0.05):
    """Darken every display by lowering its gamma ramp to `level` (0-1). Only the light the
    monitor gives off changes: screenshots and screen capture still see the normal picture, so
    the tools keep working. Windows refuses very dark ramps unless GdiIcmGammaRange allows them,
    so this steps up from `level` until each display accepts. Returns the level reached, or None."""
    steps = [level] + [s / 100 for s in range(10, 101, 5) if s / 100 > level]
    accepted = None
    for name in _displays():
        for step in steps:
            if _set_ramp(name, _linear_ramp(step)):
                accepted = max(accepted or 0, step)
                break
    if accepted is not None:
        gamma_marker().touch()
    return accepted


def restore_gamma():
    """Put every display back to the normal, linear gamma ramp."""
    for name in _displays():
        _set_ramp(name, _linear_ramp(1.0))
    try:
        gamma_marker().unlink()
    except FileNotFoundError:
        pass


# ---------- quiet mode ----------
class KeepAwake:
    """Tell Windows the PC is busy for as long as a run lasts: no sleep, no screen saver.
    Some tools click through window messages rather than the real mouse, which Windows doesn't
    count as use, so without this it could sleep or lock in the middle of a game."""
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x1, 0x2

    def _set(self, flags):
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
        except AttributeError:  # not Windows
            pass

    def __enter__(self):
        self._set(self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED | self.ES_DISPLAY_REQUIRED)
        return self

    def __exit__(self, *exc):
        self._set(self.ES_CONTINUOUS)  # back to normal
        return False


class QuietMode:
    """Mute the speakers and/or dim the screens for the duration of a run, then restore
    exactly what was there before. Each part fails soft: a missing library or an external
    monitor without DDC/CI just means that part is skipped."""

    def __init__(self, mute=True, dim=False, dim_level=0.3):
        self.mute, self.dim, self.dim_level = mute, dim, dim_level
        self._volume = self._was_muted = None
        self._brightness = None
        self._gamma = False

    def __enter__(self):
        if self.mute:
            try:
                from ctypes import POINTER, cast
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                speakers = AudioUtilities.GetSpeakers()
                # newer pycaw exposes the volume control directly; older versions need Activate()
                volume = getattr(speakers, "EndpointVolume", None)
                if volume is None:
                    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    volume = cast(interface, POINTER(IAudioEndpointVolume))
                self._volume = volume
                self._was_muted = self._volume.GetMute()
                self._volume.SetMute(1, None)
            except Exception as e:
                print(f"mute skipped: {e}")
        if self.dim:
            # hardware brightness works on laptops and DDC/CI monitors; gamma works almost
            # everywhere else, so use both
            try:
                import screen_brightness_control as sbc
                self._brightness = sbc.get_brightness()
                sbc.set_brightness(int(self.dim_level * 100))
            except Exception as e:
                print(f"brightness not changed (monitor may not support it): {e}")
            try:
                level = dim_gamma(self.dim_level)
                self._gamma = level is not None
                print(f"screen darkened to {int(level * 100)}%" if self._gamma
                      else "screen gamma not changed (the display refused it)")
            except Exception as e:
                print(f"gamma not changed: {e}")
        return self

    def __exit__(self, *exc):
        if self._volume is not None:
            try:
                self._volume.SetMute(self._was_muted, None)
            except Exception:
                pass
        if self._gamma:
            try:
                restore_gamma()
            except Exception:
                pass
        if self._brightness is not None:
            try:
                import screen_brightness_control as sbc
                for index, level in enumerate(self._brightness):
                    sbc.set_brightness(level, display=index)
            except Exception:
                pass
        return False


def shutdown(delay=5):
    time.sleep(delay)
    subprocess.run(["shutdown", "/s", "/t", "0"])


# ---------- Steam ----------
def restart_steam_if_running():
    """A Steam that is already running without admin rights makes admin-only games ask for
    elevation (a UAC prompt no script can click). Close it gracefully so that our elevated
    process starts Steam again and everything it launches inherits admin rights."""
    if not process_running("steam.exe"):
        return
    print(f"[{ts()}] Steam is already running; restarting it with admin rights")
    os.startfile("steam://exit")  # graceful exit
    for _ in range(30):
        pause(2)
        if not process_running("steam.exe"):
            return
    kill(["steam.exe"])
    pause(3)


def start_steam_elevated(wait=45):
    """Make sure Steam is running with our admin rights and signed in before a tool
    launches a Steam game directly (Steam's DRM hands the launch back to Steam)."""
    restart_steam_if_running()
    os.startfile("steam://open/main")
    pause(wait)


# ---------- lock screen ----------
def session_locked():
    """True while the lock or sign-in screen is up. Screen capture and real-mouse clicks don't
    work there, so no tool can do anything until someone signs in."""
    return process_running("LogonUI.exe")


def wait_for_unlock(max_wait=120):
    """Give Windows a moment in case it is just waking up; return False if it is still on the
    lock screen after that."""
    waited = 0
    while session_locked() and waited < max_wait:
        pause(10)
        waited += 10
    return not session_locked()
