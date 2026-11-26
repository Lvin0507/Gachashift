"""Game client updates, before and during the morning run (the "Update games first" switch).

There are two kinds of update, and a game can need both:
- Steam: Steam downloads it by itself while it is running. Steam's appmanifest_<appid>.acf
  says whether an update is waiting and how far the download has come.
- Launcher: the game's own launcher (Blue Archive's, Kuro's, HoYoPlay, GRYPHLINK) shows an
  update button where its start button usually is.

A launcher's update is done when its button looks like the start button again. How the start
button looks is learned by launch_and_click: the picture of the button just before the click
that started the game. So there is no fixed time limit: a big update just takes longer.

The update runs while the other games play: the game is moved to the end of the run, its
launcher is minimized and left alone by the other games' cleanup, and Gachashift comes back to
it when everything else is done."""

import datetime
import json
import math
import os
import re
import time

from .config import app_dir

# --- Steam --------------------------------------------------------------------------------

# appmanifest StateFlags bits
UPDATE_REQUIRED, FULLY_INSTALLED = 2, 4
UPDATE_RUNNING, UPDATE_PAUSED, UPDATE_STARTED = 256, 512, 1024


def read_acf(text):
    """The simple "key" "value" pairs of an appmanifest (nested sections are skipped)."""
    return {k.lower(): v for k, v in re.findall(r'^\s*"(\w+)"\s+"([^"]*)"\s*$', text, re.M)}


def steam_manifest(appid=None, game_path=None, libraries=None):
    """The appmanifest of a Steam game, found by app ID or by the folder its exe is in."""
    if libraries is None:
        from .finder import steam_libraries
        libraries = steam_libraries()
    game = os.path.normcase(os.path.abspath(game_path)) if game_path else ""
    for common in libraries:
        steamapps = os.path.dirname(common)
        if appid:
            path = os.path.join(steamapps, f"appmanifest_{appid}.acf")
            if os.path.isfile(path):
                return path
            continue
        if not game:
            continue
        try:
            names = os.listdir(steamapps)
        except OSError:
            continue
        for name in names:
            if not (name.startswith("appmanifest_") and name.endswith(".acf")):
                continue
            path = os.path.join(steamapps, name)
            folder = read_acf(_read(path) or "").get("installdir")
            if folder and game.startswith(os.path.normcase(os.path.join(common, folder)) + os.sep):
                return path
    return None


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def steam_state(text):
    """(needs an update, progress) from an appmanifest's text. Progress is a number that grows
    while Steam downloads and installs, to tell a moving download from a stuck one."""
    acf = read_acf(text or "")
    try:
        flags = int(acf.get("stateflags", "4"))
    except ValueError:
        flags = FULLY_INSTALLED
    busy = flags & (UPDATE_REQUIRED | UPDATE_RUNNING | UPDATE_PAUSED | UPDATE_STARTED)
    needs = bool(busy) or not flags & FULLY_INSTALLED
    progress = sum(int(acf.get(k, "0") or 0) for k in ("bytesdownloaded", "bytesstaged")
                   if (acf.get(k) or "0").isdigit())
    return needs, progress


# --- what a launcher's button looks like --------------------------------------------------

BOX = (0.16, 0.07)          # the area around the button that is compared, as window fractions
GRID = (32, 8)              # compared as this many cells of average brightness
ACTIVITY_TOP = 0.5          # progress bars and numbers live in the lower half of the window
ACTIVITY_GRID = (48, 12)


def _cells(picture, left, top, right, bottom, grid):
    pixels, width, height = picture
    cols, rows = grid
    out = []
    for row in range(rows):
        y0 = int(height * (top + (bottom - top) * row / rows))
        y1 = max(y0 + 1, int(height * (top + (bottom - top) * (row + 1) / rows)))
        for col in range(cols):
            x0 = int(width * (left + (right - left) * col / cols))
            x1 = max(x0 + 1, int(width * (left + (right - left) * (col + 1) / cols)))
            total = count = 0
            for y in range(max(0, y0), min(height, y1)):
                for x in range(max(0, x0), min(width, x1)):
                    r, g, b = pixels[y * width + x]
                    total += r * 299 + g * 587 + b * 114
                    count += 1
            out.append(total / count / 1000 if count else 0.0)
    return out


def look(picture, position):
    """The button at position (x, y fractions), as a list of cell brightnesses."""
    x, y = position
    w, h = BOX
    return _cells(picture, max(0.0, x - w / 2), max(0.0, y - h / 2),
                  min(1.0, x + w / 2), min(1.0, y + h / 2), GRID)


def activity(picture):
    return _cells(picture, 0.0, ACTIVITY_TOP, 1.0, 1.0, ACTIVITY_GRID)


def brightness(picture):
    pixels = picture[0]
    return sum(sum(p) for p in pixels) / (3 * len(pixels)) if pixels else 0.0


def same_look(a, b, min_correlation=0.9, max_shift=40):
    """True when two looks show the same button. Its shape (the text on it) must match; a
    change in brightness alone, such as the mouse hovering over it, doesn't count."""
    if not a or not b or len(a) != len(b):
        return False
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    if abs(mean_a - mean_b) > max_shift:
        return False
    da = [v - mean_a for v in a]
    db = [v - mean_b for v in b]
    spread = math.sqrt(sum(v * v for v in da) * sum(v * v for v in db))
    if spread < 1e-6:
        # flat: a button with no text on it, or a blank spot
        return all(abs(x - y) < 8 for x, y in zip(a, b))
    return sum(x * y for x, y in zip(da, db)) / spread >= min_correlation


def moved(a, b, threshold=10):
    """True when anything in the area changed (a progress bar, a number, a new screen)."""
    if not a or not b or len(a) != len(b):
        return True
    return max(abs(x - y) for x, y in zip(a, b)) > threshold


# --- the start buttons learned from successful launches -----------------------------------

def refs_file():
    return app_dir() / "launcher_buttons.json"


def _load_refs():
    try:
        return json.loads(refs_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def start_button(key):
    """(position, look) of a launcher's start button, or None if it was never learned."""
    ref = _load_refs().get(key)
    if not ref:
        return None
    return tuple(ref["position"]), ref["look"]


def remember_start_button(key, position, button_look):
    refs = _load_refs()
    refs[key] = {"position": [round(v, 4) for v in position], "look": [round(v, 1) for v in button_look],
                 "saved": datetime.date.today().isoformat()}
    try:
        refs_file().write_text(json.dumps(refs), encoding="utf-8")
    except OSError as e:
        print(f"could not remember the start button: {e}")


# --- one update ---------------------------------------------------------------------------

STEP = 30                 # seconds between looks while waiting
SETTLE = 8                # seconds after a click before looking at what it did
NUDGE_AFTER = 180         # a button and progress area both frozen this long: paused, or asking
NOT_STARTED = 360         # the button still the update button this long: it never started
MAX_NUDGES = 3
DONE_UNLEARNED = 300      # with no learned start button: the button frozen this long is done
STUCK_AFTER = 20 * 60     # no progress at all for this long: give up
MAX_HOURS = 8             # never wait longer than this for one update
DIALOG_AREA = (0.15, 0.2, 0.85, 0.92)


class Update:
    """One game's update. kind is "steam" or "launcher"; result is None while it runs, then
    "done" or the i18n key of why it failed."""

    def __init__(self, gid, kind, group=""):
        self.gid, self.kind, self.group = gid, kind, group
        self.started = time.time()
        self.result = None
        self.pids = set()

    def minutes(self):
        return max(1, round((time.time() - self.started) / 60))

    def finish(self, result):
        from .system import unprotect
        self.result = result
        unprotect(self.pids)
        return result


class SteamUpdate(Update):
    def __init__(self, gid, manifest, appid=None, clock=time.time, sleep=None, read=_read,
                 open_url=None):
        super().__init__(gid, "steam", "steam")
        self.manifest, self.appid = manifest, appid
        self.clock, self.read = clock, read
        self.sleep = sleep or _pause
        self.open_url = open_url or (lambda url: os.startfile(url))  # Windows only
        self.launched = False  # Steam was asked to start the game to get the update going
        self.started = clock()

    def wait(self, deadline_hours=MAX_HOURS):
        last, last_move = None, self.clock()
        while True:
            needs, progress = steam_state(self.read(self.manifest))
            if not needs:
                return self.finish("done")
            now = self.clock()
            if progress != last:
                last, last_move = progress, now
            if now - last_move >= STUCK_AFTER / 2 and not self.launched and self.appid:
                # Steam is set to update this game only when it's launched: launch it
                print("Steam hasn't started the update; asking Steam to start the game")
                self.open_url(f"steam://rungameid/{self.appid}")
                self.launched, last_move = True, now
            elif now - last_move >= STUCK_AFTER:
                return self.finish("hint.update_steam_idle")
            if now - self.started >= deadline_hours * 3600:
                return self.finish("hint.update_too_long")
            self.sleep(STEP)


def _pause(seconds):
    from .system import pause
    pause(seconds)


class LauncherUpdate(Update):
    """screen: what the update needs from Windows (see WindowsScreen); tests pass a fake."""

    def __init__(self, gid, screen, key, group="", clock=time.time, sleep=None):
        super().__init__(gid, "launcher", group or key)
        self.screen, self.key = screen, key
        self.clock = clock
        self.sleep = sleep or _pause
        self.started = clock()
        self.position = None
        self.update_look = None   # the button before the update was started
        self.reference = None     # the learned start button's look, if any
        self.nudges = 0

    def _picture(self):
        hwnd = self.screen.window()
        if not hwnd or not self.screen.front(hwnd):
            return hwnd, None
        self.screen.mouse_away(hwnd)
        return hwnd, self.screen.picture(hwnd)

    def check(self):
        """Look at the open launcher: "no_update", "unknown" (no learned start button and no
        update started here), or "update" with the button remembered for begin()."""
        known = start_button(self.key)
        hwnd, pic = self._picture()
        if pic is None:
            return "no_picture" if hwnd else "no_window"
        self.position, self.reference = known if known else (None, None)
        if self.position is None:
            return "unknown"
        self.update_look = look(pic, self.position)
        return "no_update" if same_look(self.update_look, self.reference) else "update"

    def begin(self):
        """Start the update in a launcher whose button isn't the start button. Returns
        "downloading", "was_start" (the click started the game: it wasn't an update), or the
        key of why it couldn't start."""
        from .buttonfind import find_button
        hwnd, pic = self._picture()
        if pic is None:
            return self.finish("hint.update_no_window")
        if self.position is None:
            known = start_button(self.key)
            self.position, self.reference = known if known else (find_button(*pic), None)
        if self.position is None:
            return self.finish("hint.update_no_button")
        before = look(pic, self.position)
        self.update_look = self.update_look or before
        # already downloading (the run's own clicks may have started it): don't click, a
        # click there would pause it
        self.sleep(5)
        hwnd, pic2 = self._picture()
        if pic2 is not None and moved(before, look(pic2, self.position)):
            return self._downloading(hwnd)
        # a second click undoes a first one that paused a download already going (one whose
        # button doesn't change while it downloads)
        for attempt in range(2):
            dialogs_before = set(self.screen.dialogs(hwnd))
            self.screen.click(hwnd, *self.position)
            self.sleep(SETTLE)
            if self.screen.game_running():
                self.finish("was_start")
                return "was_start"
            self._confirm(hwnd, dialogs_before, before, pic)
            if self._progressing():
                return self._downloading(self.screen.window() or hwnd)
            hwnd, pic = self._picture()
            if pic is None:
                break
        return self.finish("hint.update_no_progress")

    def _progressing(self, samples=6):
        """True when the button or the progress area keeps changing for a minute."""
        last = None
        for _ in range(samples):
            hwnd, pic = self._picture()
            if pic is None:
                return False
            now = (look(pic, self.position), activity(pic))
            if last and (moved(last[0], now[0]) or moved(last[1], now[1])):
                return True
            last = now
            self.sleep(10)
        return False

    def _confirm(self, hwnd, dialogs_before, before, pic_before):
        """Answer the "download now?" question some launchers ask after the click: in a
        window of its own, or drawn over the launcher (which darkens it)."""
        from .buttonfind import far_apart, find_button
        new = [d for d in self.screen.dialogs(hwnd) if d not in dialogs_before]
        if new:
            dialog = new[0]
            if self.screen.front(dialog):
                pic = self.screen.picture(dialog)
                spot = find_button(*pic, area=(0.0, 0.3, 1.0, 1.0)) if pic else None
                if spot:
                    print("a confirm window opened; clicking its button")
                    self.screen.click(dialog, *spot)
                else:
                    print("a confirm window opened; pressing Enter")
                    self.screen.enter(dialog)
                self.sleep(SETTLE)
            return
        hwnd, pic = self._picture()
        if pic is None:
            return
        unchanged = same_look(look(pic, self.position), before) and not moved(
            look(pic, self.position), before)
        darker = brightness(pic) < brightness(pic_before) * 0.85
        if unchanged or darker:
            spot = find_button(*pic, area=DIALOG_AREA)
            if spot and far_apart(spot, self.position, 0.08):
                print("the launcher is asking something; clicking its button")
                self.screen.click(hwnd, *spot)
            else:
                self.screen.enter(hwnd)
            self.sleep(SETTLE)

    def _downloading(self, hwnd):
        from .system import protect
        self.pids = set(self.screen.pids())
        protect(self.pids)
        self.screen.minimize(hwnd)
        return "downloading"

    def wait(self, deadline_hours=MAX_HOURS):
        """Wait until the button is the start button again. Returns "done" or why not."""
        if self.result:
            return self.result
        last_look = last_area = gone_since = None
        button_since = all_since = unchanged_since = self.clock()
        while True:
            now = self.clock()
            if now - self.started >= deadline_hours * 3600:
                return self.finish("hint.update_too_long")
            if self.screen.game_running():
                return self.finish("done")  # the launcher started the game after updating
            hwnd = self.screen.window(restore=True)
            if not hwnd:
                # a launcher can restart itself to finish updating; give it a moment
                gone_since = gone_since or now
                if now - gone_since > 120:
                    return self.finish("done")
                self.sleep(STEP)
                continue
            gone_since = None
            hwnd, pic = self._picture()
            if pic is None:
                self.sleep(STEP)
                continue
            button, area = look(pic, self.position), activity(pic)
            if self.reference is not None and same_look(button, self.reference):
                return self.finish("done")
            if last_look is not None and moved(last_look, button):
                button_since = all_since = now
            elif last_area is not None and moved(last_area, area):
                all_since = now
            last_look, last_area = button, area
            # a moving background can hide that nothing happened: the button itself tells
            if not same_look(button, self.update_look):
                unchanged_since = now
            if (self.reference is None and now - button_since >= DONE_UNLEARNED
                    and not same_look(button, self.update_look)):
                return self.finish("done")  # best guess: the tool will find out
            if self.nudges < MAX_NUDGES and (now - all_since >= NUDGE_AFTER
                                             or now - unchanged_since >= NOT_STARTED):
                # nothing moves: paused, or waiting for another click (install, confirm)
                self.nudges += 1
                print(f"the launcher has been still for {int(now - all_since)}s; clicking its button")
                dialogs_before = set(self.screen.dialogs(hwnd))
                self.screen.click(hwnd, *self.position)
                self.sleep(SETTLE)
                if self.screen.game_running():
                    if self.reference is None:
                        remember_start_button(self.key, self.position, button)
                    return self.finish("done")
                self._confirm(hwnd, dialogs_before, button, pic)
                button_since = all_since = unchanged_since = self.clock()
                last_look = last_area = None
            elif now - all_since >= STUCK_AFTER:
                return self.finish("hint.update_stuck")
            self.screen.minimize(hwnd)
            self.sleep(STEP)


class WindowsScreen:
    """A launcher's windows, found by exe name or by a function that lists its processes."""

    def __init__(self, exe=None, processes=None, game_exes=()):
        self.exe, self.processes, self.game_exes = exe, processes, game_exes
        self.hwnd = None

    def pids(self):
        from .system import pids_of
        if self.processes:
            return {p.pid for p in self.processes()}
        return pids_of(self.exe) if self.exe else set()

    def window(self, restore=False):
        from .system import main_window_of
        from .system import restore as show
        if restore and self.hwnd:
            show(self.hwnd)
            time.sleep(1)
        found = main_window_of(pids=self.pids())
        if found:
            self.hwnd = found
        return found

    def front(self, hwnd):
        from .system import bring_to_front
        return bring_to_front(hwnd)

    def mouse_away(self, hwnd):
        from .system import move_mouse_to
        move_mouse_to(hwnd, 0.02, 0.5)  # off the button, so it isn't drawn as hovered
        time.sleep(0.4)

    def picture(self, hwnd):
        from .buttonfind import grab_client
        try:
            return grab_client(hwnd, max_width=480)
        except Exception as e:
            print(f"could not look at the launcher: {type(e).__name__}: {e}")
            return None

    def click(self, hwnd, fx, fy):
        from .system import click_in_window
        return click_in_window(hwnd, fx, fy)

    def enter(self, hwnd):
        from .system import press_enter
        press_enter(hwnd)

    def minimize(self, hwnd):
        from .system import minimize
        minimize(hwnd)

    def dialogs(self, main):
        from .system import windows_of
        return [h for h, _ in windows_of(self.pids()) if h != main]

    def game_running(self):
        from .system import process_running
        return any(process_running(n) for n in self.game_exes if n)


# --- the run's updates --------------------------------------------------------------------

class Updates:
    """Every update in one run: started by the check before the games, or when a game's
    launcher turned out to be showing an update instead of starting it."""

    def __init__(self, log=print):
        self.log = log
        self.pending = {}   # game id -> Update still downloading
        self.failed = {}    # game id -> why its update couldn't start (an i18n key)

    # -- before the games --
    def before_run(self, games, open_wait=120, settle=20):
        """games: Game objects due in this run."""
        from .system import kill, pause, process_running, start_steam_elevated
        steam_started = False
        for game in games:
            game.updater = self
            app = game.steam_app()
            manifest = steam_manifest(*app) if app else None
            if manifest and steam_state(_read(manifest))[0]:
                self.log(f"{game.id}: Steam has an update waiting; letting Steam download it")
                if not steam_started:
                    start_steam_elevated()
                    steam_started = True
                self.pending[game.id] = SteamUpdate(game.id, manifest, app[0])
                continue
            opener, key = game.open_launcher(), game.launcher_key()
            if not opener or not key:
                continue
            if start_button(key) is None:
                self.log(f"{game.id}: its start button hasn't been seen yet (it is learned the "
                         "first time the game starts); not checking for an update this time")
                continue
            self.log(f"{game.id}: opening the launcher to check for an update")
            opener()
            screen = game.launcher_screen()
            waited = 0
            while not screen.window() and waited < open_wait:
                pause(5)
                waited += 5
            pause(settle)  # launchers check for updates themselves when they open
            update = LauncherUpdate(game.id, screen, key, game.launcher_group())
            found = "no_window"
            for _ in range(3):
                found = update.check()
                if found != "update":
                    break
                pause(10)  # make sure: it may still have been starting up
            if found == "update":
                self.log(f"{game.id}: the launcher shows an update; starting it")
                self._started(game, update, update.begin())
                if game.id in self.pending:
                    continue
            elif found in ("no_window", "no_picture"):
                self.log(f"{game.id}: couldn't look at the launcher ({found}); not checking this time")
            else:
                self.log(f"{game.id}: no update ({found})")
            kill(list(game.launcher_exes()) + list(game.game_exes()))
            if any(process_running(n) for n in game.game_exes() if n):
                pause(3)

    def _started(self, game, update, result):
        if result == "downloading":
            self.pending[game.id] = update
            return update
        if result == "was_start":
            # the launcher looked different but the click started the game: the start button
            # has a new look (a redesigned launcher), so learn it
            if update.position and update.update_look:
                remember_start_button(update.key, update.position, update.update_look)
            return None
        self.failed[game.id] = result
        return None

    # -- during a game's cleanup --
    def start_in_run(self, game):
        """The game's launcher was left open without the game: start its update if it shows
        one. Returns the Update, or None."""
        if game.id in self.pending:
            return None
        self.log(f"{game.id}: the launcher was left open; looking for an update")
        update = LauncherUpdate(game.id, game.launcher_screen(), game.launcher_key(),
                                game.launcher_group())
        if update.check() == "no_update":
            return None
        return self._started(game, update, update.begin())

    # -- deciding what runs when --
    def blocking(self, game):
        """The unfinished update this game has to wait for: its own, or one in the same
        launcher (GRYPHLINK serves both Endfield and Arknights)."""
        own = self.pending.get(game.id)
        if own and own.result is None:
            return own
        group = game.launcher_group()
        for update in self.pending.values():
            if update.result is None and group and update.group == group:
                return update
        return None

    def take(self, gid):
        """This game's own update, if it had one, removed from the run's list."""
        return self.pending.pop(gid, None)

    def finish_all(self):
        """At the end of the run: nothing stays protected from cleanup."""
        for update in self.pending.values():
            if update.result is None:
                update.finish("hint.update_too_long")
