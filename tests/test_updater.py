"""Game client updates: Steam's manifests, launcher buttons, and the run waiting for them."""

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gachashift import report as R
from gachashift import runner, system, updater
from gachashift.config import DEFAULT_CONFIG
from gachashift.games.base import Game

W, H = 160, 90
BUTTON = (0.8, 0.85)
YELLOW, DARK, BACK = (230, 190, 60), (30, 30, 30), (40, 40, 60)
TEXT = {"start": (0.15, 0.3, 0.45, 0.6, 0.75), "update": (0.25, 0.55), "pause": (0.45, 0.5)}


def picture(text="start", progress=None, dim=False, dialog=False, hover=False):
    """A launcher window: a yellow button in the lower right with "text" on it (dark bars
    standing in for letters), an optional progress bar under it and a dialog button."""
    pixels = [BACK] * (W * H)

    def fill(x0, y0, x1, y1, colour):
        for y in range(int(y0 * H), int(y1 * H)):
            for x in range(int(x0 * W), int(x1 * W)):
                pixels[y * W + x] = colour

    button = tuple(min(255, c + 20) for c in YELLOW) if hover else YELLOW
    fill(0.7, 0.8, 0.9, 0.9, button)
    # "p3": a button showing a changing number (bars move with it)
    spots = (int(text[1:]) / 10,) if text[:1] == "p" and text[1:].isdigit() else TEXT.get(text, ())
    for spot in spots:
        x = 0.7 + 0.2 * spot
        fill(x, 0.83, x + 0.012, 0.87, DARK)
    if progress is not None:
        fill(0.05, 0.94, 0.05 + 0.9 * progress, 0.97, (250, 250, 250))
    if dim:  # a question drawn over the launcher darkens everything behind it
        pixels = [tuple(c // 2 for c in p) for p in pixels]
    if dialog:
        fill(0.25, 0.3, 0.75, 0.7, (70, 70, 80))
        fill(0.52, 0.55, 0.68, 0.64, (40, 120, 230))
    return pixels, W, H


def dialog_window():
    """A confirm window of its own: a grey box with a blue button in its lower right."""
    pixels = [(60, 60, 70)] * (W * H)
    for y in range(int(0.7 * H), int(0.82 * H)):
        for x in range(int(0.55 * W), int(0.75 * W)):
            pixels[y * W + x] = (40, 120, 230)
    return pixels, W, H


class LookTest(unittest.TestCase):
    def test_same_button_even_when_hovered(self):
        a = updater.look(picture("start"), BUTTON)
        b = updater.look(picture("start", hover=True), BUTTON)
        self.assertTrue(updater.same_look(a, b))

    def test_update_button_is_different(self):
        a = updater.look(picture("start"), BUTTON)
        b = updater.look(picture("update"), BUTTON)
        self.assertFalse(updater.same_look(a, b))

    def test_progress_is_movement(self):
        a = updater.activity(picture("pause", progress=0.2))
        b = updater.activity(picture("pause", progress=0.3))
        self.assertTrue(updater.moved(a, b))
        self.assertFalse(updater.moved(a, updater.activity(picture("pause", progress=0.2))))


ACF = '''"AppState"
{
\t"appid"\t\t"3513350"
\t"installdir"\t\t"Wuthering Waves"
\t"StateFlags"\t\t"%d"
\t"BytesDownloaded"\t\t"%d"
\t"BytesStaged"\t\t"0"
\t"UserConfig"
\t{
\t\t"language"\t\t"english"
\t}
}
'''


class SteamTest(unittest.TestCase):
    def test_state(self):
        self.assertEqual(updater.steam_state(ACF % (4, 0)), (False, 0))
        self.assertEqual(updater.steam_state(ACF % (6, 0)), (True, 0))
        self.assertEqual(updater.steam_state(ACF % (1030, 500)), (True, 500))
        self.assertEqual(updater.steam_state(""), (False, 0))

    def test_manifest_by_appid_and_by_game_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            common = os.path.join(tmp, "steamapps", "common")
            os.makedirs(os.path.join(common, "Wuthering Waves"))
            Path(tmp, "steamapps", "appmanifest_3513350.acf").write_text(ACF % (4, 0), encoding="utf-8")
            expected = os.path.join(tmp, "steamapps", "appmanifest_3513350.acf")
            self.assertEqual(updater.steam_manifest("3513350", libraries=[common]), expected)
            exe = os.path.join(common, "Wuthering Waves", "Client", "Client.exe")
            self.assertEqual(updater.steam_manifest(None, exe, libraries=[common]), expected)
            self.assertIsNone(updater.steam_manifest(None, "D:/Other/game.exe", libraries=[common]))
            self.assertIsNone(updater.steam_manifest("1", libraries=[common]))

    def wait(self, states):
        clock = [0.0]
        launched = []
        states = iter(states)
        update = updater.SteamUpdate("wuthering", "x.acf", "3513350", clock=lambda: clock[0],
                                     sleep=lambda s: clock.__setitem__(0, clock[0] + s),
                                     read=lambda path: next(states), open_url=launched.append)
        return update.wait(), launched, update

    def test_waits_until_installed(self):
        result, launched, update = self.wait([ACF % (1030, n) for n in range(0, 500, 100)] + [ACF % (4, 0)])
        self.assertEqual((result, launched), ("done", []))

    def test_idle_steam_is_asked_to_start_the_game_then_given_up_on(self):
        result, launched, _ = self.wait([ACF % (6, 0)] * 200)
        self.assertEqual(result, "hint.update_steam_idle")
        self.assertEqual(launched, ["steam://rungameid/3513350"])


class FakeScreen:
    """A launcher that goes through a script: what it shows after each click."""

    def __init__(self, shows, on_click=None, dialogs=()):
        self.shows = shows          # list of pictures; the last one stays
        self.step = 0
        self.on_click = on_click or (lambda screen, hwnd, spot: None)
        self.clicks, self.enters, self.minimized = [], [], 0
        self.open_dialogs = list(dialogs)
        self.game = False
        self.dialog_picture = None

    def pids(self):
        return {4242}

    def window(self, restore=False):
        return 1

    def front(self, hwnd):
        return True

    def mouse_away(self, hwnd):
        pass

    def picture(self, hwnd):
        if hwnd != 1:
            return self.dialog_picture
        pic = self.shows[min(self.step, len(self.shows) - 1)]
        self.step += 1
        return pic

    def click(self, hwnd, fx, fy):
        self.clicks.append((hwnd, round(fx, 2), round(fy, 2)))
        self.on_click(self, hwnd, (fx, fy))
        return True

    def enter(self, hwnd):
        self.enters.append(hwnd)

    def minimize(self, hwnd):
        self.minimized += 1

    def dialogs(self, main):
        return list(self.open_dialogs)

    def game_running(self):
        return self.game


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(updater, "refs_file", lambda: Path(self.tmp.name) / "refs.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(system._PROTECTED.clear)
        self.clock = [0.0]

    def make(self, screen, learned=True):
        if learned:
            updater.remember_start_button("ba:launcher.exe", BUTTON, updater.look(picture("start"), BUTTON))
        return updater.LauncherUpdate("bluearchive", screen, "ba:launcher.exe", clock=lambda: self.clock[0],
                                      sleep=lambda s: self.clock.__setitem__(0, self.clock[0] + s))

    def downloading_after_click(self):
        """Shows the update button until clicked, then a moving progress bar, then start."""
        frames = [picture("pause", progress=p / 10) for p in range(10)]
        screen = FakeScreen([picture("update")] * 3)

        def clicked(screen, hwnd, spot):
            screen.shows = frames + [picture("start")]
            screen.step = 0
        screen.on_click = clicked
        return screen

    def test_check(self):
        self.assertEqual(self.make(FakeScreen([picture("start")])).check(), "no_update")
        self.assertEqual(self.make(FakeScreen([picture("update")])).check(), "update")

    def test_check_before_the_start_button_is_learned(self):
        self.assertEqual(self.make(FakeScreen([picture("update")]), learned=False).check(), "unknown")

    def test_update_clicked_once_then_waited_for(self):
        screen = self.downloading_after_click()
        update = self.make(screen)
        update.check()
        self.assertEqual(update.begin(), "downloading")
        self.assertEqual(len(screen.clicks), 1)
        self.assertEqual(system._PROTECTED, {4242})   # other games' cleanup leaves it alone
        self.assertEqual(update.wait(), "done")
        self.assertEqual(len(screen.clicks), 1)       # never clicked while downloading
        self.assertEqual(system._PROTECTED, set())

    def test_already_downloading_is_not_clicked(self):
        screen = FakeScreen([picture(f"p{p}", progress=p / 10) for p in range(10)] + [picture("start")])
        update = self.make(screen)
        self.assertEqual(update.begin(), "downloading")
        self.assertEqual(screen.clicks, [])

    def test_confirm_window_gets_its_button_clicked(self):
        frames = [picture("pause", progress=p / 10) for p in range(10)]
        screen = FakeScreen([picture("update")] * 20)

        def clicked(screen, hwnd, spot):
            if hwnd == 1:
                screen.open_dialogs = [2]         # "Download 30 GB now?"
            else:
                screen.open_dialogs = []
                screen.shows, screen.step = frames, 0
        screen.on_click = clicked
        screen.dialog_picture = dialog_window()
        update = self.make(screen)
        self.assertEqual(update.begin(), "downloading")
        self.assertEqual([c[0] for c in screen.clicks], [1, 2])
        self.assertEqual(screen.clicks[1][1:], (0.65, 0.75))  # the dialog's blue button

    def test_question_drawn_over_the_launcher(self):
        frames = [picture("pause", progress=p / 10) for p in range(10)]
        screen = FakeScreen([picture("update")] * 20)

        def clicked(screen, hwnd, spot):
            if spot[1] > 0.8:   # the update button: the launcher darkens and asks
                screen.shows, screen.step = [picture("update", dim=True, dialog=True)], 0
            else:
                screen.shows, screen.step = frames, 0
        screen.on_click = clicked
        update = self.make(screen)
        self.assertEqual(update.begin(), "downloading")
        self.assertEqual(len(screen.clicks), 2)

    def test_click_that_starts_the_game_was_no_update(self):
        screen = FakeScreen([picture("update")] * 5)
        screen.on_click = lambda s, h, spot: setattr(s, "game", True)
        self.assertEqual(self.make(screen).begin(), "was_start")

    def test_nothing_happens(self):
        screen = FakeScreen([picture("update")] * 50)
        update = self.make(screen)
        self.assertEqual(update.begin(), "hint.update_no_progress")
        self.assertEqual(len(screen.clicks), 2)
        self.assertEqual(screen.enters, [1, 1])

    def test_click_that_paused_a_download_is_undone(self):
        # the progress bar was moving under a button that doesn't change; the first click
        # paused it, the second resumes it
        moving = [picture("pause", progress=p / 20) for p in range(20)]
        screen = FakeScreen(moving)
        state = {"paused": False}

        def clicked(screen, hwnd, spot):
            state["paused"] = not state["paused"]
            screen.shows = [picture("pause", progress=0.3)] * 20 if state["paused"] else moving
            screen.step = 0
        screen.on_click = clicked
        update = self.make(screen)
        self.assertEqual(update.begin(), "downloading")
        self.assertFalse(state["paused"])

    def test_paused_download_is_nudged(self):
        moving = [picture("pause", progress=p / 10) for p in range(5)]
        screen = FakeScreen(moving + [picture("update", progress=0.5)] * 20)

        def resumed(screen, hwnd, spot):
            screen.shows = [picture("pause", progress=0.5 + p / 20) for p in range(8)] + [picture("start")]
            screen.step = 0
        screen.on_click = resumed
        update = self.make(screen)
        update.check()
        update.position, update.update_look = BUTTON, updater.look(picture("update"), BUTTON)
        self.assertEqual(update.wait(), "done")
        self.assertEqual(len(screen.clicks), 1)

    def test_without_a_learned_button_a_still_new_button_is_done(self):
        frames = [picture("pause", progress=p / 10) for p in range(10)]
        screen = FakeScreen(frames + [picture("start")] * 100)
        update = self.make(screen, learned=False)
        update.position, update.update_look = BUTTON, updater.look(picture("update"), BUTTON)
        self.assertEqual(update.wait(), "done")

    def test_update_that_never_started_behind_a_moving_background(self):
        # the window keeps changing (an animated background), but the button is still the
        # update button six minutes later: click it again
        moving = [picture("update", progress=(p % 7) / 10) for p in range(30)]
        screen = FakeScreen(moving)

        def started(screen, hwnd, spot):
            screen.shows = [picture(f"p{p % 10}") for p in range(10)] + [picture("start")]
            screen.step = 0
        screen.on_click = started
        update = self.make(screen)
        update.check()
        self.assertEqual(update.wait(), "done")
        self.assertEqual(len(screen.clicks), 1)
        self.assertGreaterEqual(self.clock[0], updater.NOT_STARTED)

    def test_stuck(self):
        screen = FakeScreen([picture("update", progress=0.5)] * 500)
        update = self.make(screen)
        update.check()
        self.assertEqual(update.wait(), "hint.update_stuck")
        self.assertEqual(len(screen.clicks), updater.MAX_NUDGES)


class KillTest(unittest.TestCase):
    def test_protected_launcher_survives_cleanup(self):
        killed = []

        class P:
            def __init__(self, pid, name):
                self.pid, self.info = pid, {"name": name}

            def kill(self):
                killed.append(self.pid)
        procs = [P(1, "Launcher.exe"), P(2, "Launcher.exe"), P(3, "Game.exe")]
        system.protect({2})
        try:
            with mock.patch.object(system.psutil, "process_iter", lambda attrs: procs):
                system.kill(["launcher.exe", "Game.exe"])
                system.kill_processes(procs)
        finally:
            system.unprotect({2})
        self.assertEqual(killed, [1, 3, 1, 3])


class LaunchAndClickTest(unittest.TestCase):
    """The start button is learned from the click that started the game, and in careful mode
    a button that steadily looks different isn't clicked."""

    def run_launcher(self, looks, careful, known=None, game_after=None):
        state = {"clicks": 0, "saved": None, "checks": 0}
        looks = iter(looks)

        def running(name):
            state["checks"] += 1
            return game_after is not None and state["clicks"] >= game_after

        with mock.patch.multiple(system, pause=lambda s: None, process_running=running,
                                 main_window_of=lambda exe: 1, bring_to_front=lambda h: True,
                                 make_dpi_aware=lambda: None,
                                 click_in_window=lambda h, x, y: state.__setitem__("clicks", state["clicks"] + 1) or True), \
                mock.patch.object(updater, "start_button", lambda key: known), \
                mock.patch.object(updater, "remember_start_button",
                                  lambda key, pos, lk: state.__setitem__("saved", (key, pos, lk))), \
                mock.patch.object(system.time, "time", side_effect=[i * 10.0 for i in range(1000)]):
            ok = system.launch_and_click(lambda: None, "launcher.exe", BUTTON, "game.exe", wait_after=0,
                                         remember="ba:launcher.exe", careful=careful,
                                         see=lambda h, p: next(looks))
        return ok, state

    def test_learns_the_look_that_started_the_game(self):
        start = updater.look(picture("start"), BUTTON)
        ok, state = self.run_launcher([start] * 5, careful=False, game_after=1)
        self.assertTrue(ok)
        self.assertEqual(state["saved"], ("ba:launcher.exe", BUTTON, start))

    def test_careful_mode_leaves_an_update_alone(self):
        start = updater.look(picture("start"), BUTTON)
        update = updater.look(picture("update"), BUTTON)
        ok, state = self.run_launcher([update] * 50, careful=True, known=(BUTTON, start))
        self.assertFalse(ok)
        self.assertEqual(state["clicks"], 0)

    def test_careful_mode_still_clicks_the_start_button(self):
        start = updater.look(picture("start"), BUTTON)
        ok, state = self.run_launcher([start] * 5, careful=True, known=(BUTTON, start), game_after=1)
        self.assertTrue(ok)
        self.assertEqual(state["clicks"], 1)


class FakeUpdate:
    def __init__(self, gid, kind="launcher", group=""):
        self.gid, self.kind, self.group, self.result = gid, kind, group, None

    def wait(self):
        self.result = "done"
        return "done"

    def minutes(self):
        return 25


class FakeUpdates:
    def __init__(self, before=()):
        self.pending = {gid: FakeUpdate(gid, "steam") for gid in before}
        self.failed = {}
        self.finished = False

    def before_run(self, games):
        pass

    def blocking(self, game):
        own = self.pending.get(game.id)
        return own if own and own.result is None else None

    def take(self, gid):
        return self.pending.pop(gid, None)

    def finish_all(self):
        self.finished = True


class RunnerTest(unittest.TestCase):
    def config(self, *gids):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        for gid in cfg["games"]:
            cfg["games"][gid] = {"enabled": gid in gids, "days": list(range(7))}
        cfg["order"] = list(gids)
        return cfg

    def make(self, gid, plays, update_first_time=False):
        class Fake(Game):
            id = gid
            calls = 0

            def run(self):
                type(self).calls += 1
                plays.append(gid)
                rep = self.new_report()
                if update_first_time and type(self).calls == 1:
                    rep.add("task", R.FAIL)
                    self.update = FakeUpdate(gid)
                    self.updater.pending[gid] = self.update
                else:
                    rep.add("task", R.OK)
                return rep
        return Fake

    def play(self, games, updates):
        cfg = self.config(*[g.id for g in games])
        with mock.patch.object(runner, "ordered", lambda cfg: games):
            return runner.run_games(cfg, None, "en", {"mute": False}, lambda m: None, updates=updates)

    def test_steam_update_runs_last_and_keeps_its_place(self):
        plays = []
        games = [self.make("arknights", plays), self.make("zzz", plays), self.make("genshin", plays)]
        updates = FakeUpdates(before=["arknights"])
        reports, stopped = self.play(games, updates)
        self.assertEqual(plays, ["zzz", "genshin", "arknights"])
        self.assertEqual([r.game for r in reports], ["arknights", "zzz", "genshin"])
        self.assertIn(("note.updated", {"source": "hint.update_steam", "minutes": 25}), reports[0].notes)
        self.assertEqual(R.outcome(reports[0]), "ok")
        self.assertTrue(updates.finished)

    def test_update_found_during_the_run(self):
        plays = []
        games = [self.make("bluearchive", plays, update_first_time=True), self.make("zzz", plays)]
        reports, _ = self.play(games, FakeUpdates())
        self.assertEqual(plays, ["bluearchive", "zzz", "bluearchive"])
        self.assertEqual(R.outcome(reports[0]), "ok")
        self.assertEqual(reports[0].notes[0][0], "note.updated")
        self.assertNotIn("note.retried", [k for k, _ in reports[0].notes])

    def test_failed_update_is_reported(self):
        plays = []
        updates = FakeUpdates()
        updates.failed["zzz"] = "hint.update_no_button"
        reports, _ = self.play([self.make("zzz", plays)], updates)
        self.assertEqual(reports[0].notes[0], ("note.update_failed", {"reason": "hint.update_no_button"}))

    def test_texts_exist(self):
        from gachashift.i18n import STRINGS
        for lang in ("en", "zh"):
            for key in ("note.updated", "note.update_failed", "tray.checking_updates",
                        "tray.waiting_update", "tray.running_after_update", "log.after_update",
                        "log.waiting_update", "action.update_failed", "compact.updated",
                        "general.update_games", "general.update_games_hint",
                        "hint.update_steam", "hint.update_launcher", "hint.update_stuck",
                        "hint.update_steam_idle", "hint.update_too_long", "hint.update_no_progress",
                        "hint.update_no_button", "hint.update_no_window"):
                self.assertIn(key, STRINGS[lang], (lang, key))


if __name__ == "__main__":
    unittest.main()


class BeforeRunTest(unittest.TestCase):
    """The check before the games: Steam first, then the launchers Gachashift can open."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(system._PROTECTED.clear)
        patcher = mock.patch.object(updater, "refs_file", lambda: Path(self.tmp.name) / "refs.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.killed, self.steam = [], []
        patcher = mock.patch.multiple(system, pause=lambda s: None, kill=self.killed.extend,
                                      process_running=lambda n: False,
                                      start_steam_elevated=lambda: self.steam.append(1))
        patcher.start()
        self.addCleanup(patcher.stop)

    def game(self, screen=None, steam=None, opened=None):
        class Fake(Game):
            id = "bluearchive"

            def launcher_exes(self):
                return ("BlueArchive Launcher.exe",)

            def game_exes(self):
                return ("BlueArchive.exe",)

            def steam_app(self):
                return steam

            def open_launcher(self):
                return (lambda: opened.append(1)) if opened is not None else None

            def launcher_screen(self):
                return screen
        return Fake({})

    def test_steam_update_waits_and_skips_the_launcher(self):
        manifest = Path(self.tmp.name, "appmanifest_1.acf")
        manifest.write_text(ACF % (6, 0), encoding="utf-8")
        opened = []
        updates = updater.Updates(log=lambda m: None)
        with mock.patch.object(updater, "steam_manifest", lambda appid, path: str(manifest)):
            updates.before_run([self.game(steam=("1", ""), opened=opened)])
        self.assertEqual(updates.pending["bluearchive"].kind, "steam")
        self.assertEqual((self.steam, opened), ([1], []))

    def test_launcher_with_an_update(self):
        updater.remember_start_button("bluearchive:bluearchive launcher.exe", BUTTON,
                                      updater.look(picture("start"), BUTTON))
        frames = [picture("pause", progress=p / 10) for p in range(10)]
        screen = FakeScreen([picture("update")] * 20)

        def clicked(screen, hwnd, spot):
            screen.shows, screen.step = frames, 0
        screen.on_click = clicked
        opened = []
        updates = updater.Updates(log=lambda m: None)
        updates.before_run([self.game(screen=screen, opened=opened)])
        self.assertEqual(opened, [1])
        self.assertEqual(updates.pending["bluearchive"].kind, "launcher")
        self.assertEqual(self.killed, [])   # left open to download

    def test_launcher_without_an_update_is_closed(self):
        updater.remember_start_button("bluearchive:bluearchive launcher.exe", BUTTON,
                                      updater.look(picture("start"), BUTTON))
        screen = FakeScreen([picture("start")] * 5)
        updates = updater.Updates(log=lambda m: None)
        updates.before_run([self.game(screen=screen, opened=[])])
        self.assertEqual(updates.pending, {})
        self.assertEqual(screen.clicks, [])
        self.assertEqual(self.killed, ["BlueArchive Launcher.exe", "BlueArchive.exe"])

    def test_not_opened_before_its_start_button_is_learned(self):
        opened = []
        updates = updater.Updates(log=lambda m: None)
        updates.before_run([self.game(screen=FakeScreen([picture("update")]), opened=opened)])
        self.assertEqual((opened, updates.pending), ([], {}))

    def test_update_found_at_cleanup(self):
        frames = [picture("pause", progress=p / 10) for p in range(10)]
        screen = FakeScreen([picture("update")] * 20)
        screen.on_click = lambda s, h, spot: (setattr(s, "shows", frames), setattr(s, "step", 0))
        updates = updater.Updates(log=lambda m: None)
        game = self.game(screen=screen)
        game.updater = updates
        game.launcher_left = True
        with mock.patch("gachashift.games.base.process_running", lambda n: n.startswith("BlueArchive L")):
            game.check_launcher()
        self.assertIs(game.update, updates.pending["bluearchive"])
        self.assertIs(updates.blocking(game), game.update)
