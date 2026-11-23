"""Windows settings that make a morning run fail without warning, checked ahead of time.

Each check returns a Problem (an i18n key, its values, and a Settings page that fixes it).
powercfg prints its labels in the system language, so only its 0x values are read."""

import re
import subprocess
from dataclasses import dataclass, field

import psutil

SETTINGS_SLEEP = "ms-settings:powersleep"
SETTINGS_LOCK = "ms-settings:lockscreen"
SETTINGS_LID = "control.exe /name Microsoft.PowerOptions /page pageGlobalSettings"


@dataclass
class Problem:
    key: str                                   # health.<name> in i18n
    params: dict = field(default_factory=dict)
    fix: str = ""                              # what opens the right Windows settings


def setting_values(output):
    """(plugged in, on battery) values from `powercfg /q ...` for one setting: the last two
    0x numbers, whatever language the labels are in."""
    values = re.findall(r"0x([0-9a-fA-F]{8})", output)
    if len(values) < 2:
        return None
    return int(values[-2], 16), int(values[-1], 16)


def query(subgroup, setting):
    try:
        out = subprocess.run(["powercfg", "/q", "SCHEME_CURRENT", subgroup, setting],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return setting_values(out.stdout) if out.returncode == 0 else None


def has_lid():
    """Laptops have a battery; desktops (which have no lid) don't."""
    try:
        return psutil.sensors_battery() is not None
    except Exception:
        return False


def secure_screen_saver():
    """True when a screen saver is on and asks for the password when it ends."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
            active = winreg.QueryValueEx(key, "ScreenSaveActive")[0]
            secure = winreg.QueryValueEx(key, "ScreenSaverIsSecure")[0]
        return str(active) == "1" and str(secure) == "1"
    except (ImportError, OSError):
        return False


def check(query=query, has_lid=has_lid, secure_screen_saver=secure_screen_saver):
    """Every problem found, worst first. The helpers are parameters so tests can fake them."""
    problems = []
    lock = query("SUB_NONE", "CONSOLELOCK")
    asks_password = lock is None or lock[0] != 0
    sleep = query("SUB_SLEEP", "STANDBYIDLE")
    hibernate = query("SUB_SLEEP", "HIBERNATEIDLE")
    # The schedule wakes a sleeping PC, but then Windows waits at the sign-in screen,
    # where no tool can see or click anything. Sleeping is only fine without the password.
    for values, key in ((sleep, "health.sleep"), (hibernate, "health.hibernate")):
        if values and values[0] and asks_password:
            problems.append(Problem(key, {"minutes": values[0] // 60}, SETTINGS_SLEEP))
    if secure_screen_saver():
        problems.append(Problem("health.screen_saver", fix=SETTINGS_LOCK))
    if has_lid():
        lid = query("SUB_BUTTONS", "LIDACTION")
        if lid and lid[0] != 0:  # 0 = do nothing
            problems.append(Problem("health.lid", fix=SETTINGS_LID))
    return problems
