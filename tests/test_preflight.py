"""The one-button check, the client-update hint, and the run's status line for the tray."""

import copy
import unittest
from unittest import mock

from gachashift import preflight, runner, system
from gachashift import report as R
from gachashift.config import DEFAULT_CONFIG
from gachashift.games.base import Game
from gachashift.health import Problem


class Response:
    def __init__(self, code):
        self.status_code = code


def config(telegram=False, discord=False, games=("zzz",)):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["telegram"] = {"enabled": telegram, "bot_token": "123:SECRET", "chat_id": "42"}
    cfg["discord"] = {"enabled": discord, "webhook_url": "https://discord.com/api/webhooks/1/SECRET"}
    for gid in cfg["games"]:
        cfg["games"][gid]["enabled"] = gid in games
    return cfg


class PreflightTest(unittest.TestCase):
    def check(self, cfg, missing=lambda gid, g: [], scheduled=lambda: "06:00",
              post=lambda *a, **k: Response(200), windows=(), tools=()):
        return preflight.check(cfg, "test", health_check=lambda: list(windows),
                               tool_check=lambda cfg: list(tools), scheduled=scheduled,
                               missing=missing, post=post)

    def test_all_good(self):
        self.assertEqual(self.check(config(telegram=True)), ([], ["Telegram"]))

    def test_everything_wrong(self):
        problems, reached = self.check(
            config(games=()), scheduled=lambda: None,
            windows=[Problem("health.lid")], tools=[Problem("tool.power", game="zzz")])
        self.assertEqual([p.key for p in problems],
                         ["preflight.no_games", "preflight.no_schedule", "health.lid", "tool.power"])
        self.assertEqual(reached, [])

    def test_missing_settings_per_game(self):
        problems, _ = self.check(config(games=("zzz", "genshin")),
                                 missing=lambda gid, g: ["od_dir"] if gid == "zzz" else [])
        self.assertEqual([(p.key, p.game, p.params) for p in problems],
                         [("preflight.missing", "zzz", {"items": ["od_dir"]})])

    def test_send_failures_never_show_the_secret(self):
        def post(url, **kwargs):
            if "telegram" in url:
                return Response(401)
            raise ConnectionError(f"could not reach {url}")
        problems, reached = self.check(config(telegram=True, discord=True), post=post)
        self.assertEqual(reached, [])
        self.assertEqual([p.params for p in problems],
                         [{"channel": "Telegram", "error": "HTTP 401"},
                          {"channel": "Discord", "error": "ConnectionError"}])
        self.assertNotIn("SECRET", repr(problems))

    def test_messages_exist_in_both_languages(self):
        from gachashift.i18n import STRINGS
        for lang in ("en", "zh"):
            for key in ("preflight.missing", "preflight.no_schedule", "preflight.send_failed",
                        "note.maybe_update", "action.update_client", "tray.running"):
                self.assertIn(key, STRINGS[lang], (lang, key))


class Launcher(Game):
    id = "zzz"

    def game_exes(self):
        return ("Game.exe",)

    def launcher_exes(self):
        return ("Launcher.exe",)


class ClientUpdateTest(unittest.TestCase):
    def left(self, running):
        game = Launcher({})
        with mock.patch("gachashift.games.base.process_running", lambda name: name in running):
            game.capture()
        return game.launcher_left

    def test_launcher_without_game(self):
        self.assertTrue(self.left({"Launcher.exe"}))

    def test_game_running(self):
        self.assertFalse(self.left({"Launcher.exe", "Game.exe"}))

    def test_nothing_open(self):
        self.assertFalse(self.left(set()))

    def test_report_and_action(self):
        game = Launcher({})
        game.launcher_left = True
        rep = R.GameReport("zzz")
        rep.add("一条龙", R.FAIL)
        runner.explain(rep, {}, game)
        self.assertIn(("note.maybe_update", {}), rep.notes)
        self.assertEqual(R.actions(rep, "en")[0].split(":")[0], "Zenless Zone Zero")
        self.assertIn("update", R.actions(rep, "en")[0])

    def test_good_run_gets_no_hint(self):
        game = Launcher({})
        game.launcher_left = True
        rep = R.GameReport("zzz")
        rep.add("一条龙", R.OK)
        runner.explain(rep, {}, game)
        self.assertEqual(rep.notes, [])


class StatusTest(unittest.TestCase):
    def test_status_lines(self):
        def make(gid, status):
            class Fake(Game):
                id = gid

                def run(self):
                    rep = self.new_report()
                    rep.add("task", status)
                    return rep
            return Fake

        cfg = copy.deepcopy(DEFAULT_CONFIG)
        for gid in ("arknights", "zzz"):
            cfg["games"][gid] = {"enabled": True, "days": list(range(7))}
        lines = []
        with mock.patch.object(runner, "ordered",
                               lambda cfg: [make("arknights", R.OK), make("zzz", R.FAIL)]):
            runner.run_games(cfg, None, "en", {"mute": False}, lambda m: None, status=lines.append)
        self.assertEqual(lines, ["Running Arknights (1/2)", "Running Zenless Zone Zero (2/2)",
                                 "Trying Zenless Zone Zero once more"])

    def test_pause_keeps_the_tray_alive(self):
        calls = []
        system.set_pump(lambda: calls.append(1))
        try:
            with mock.patch.object(system, "stop_requested", lambda: False):
                system.pause(0)
        finally:
            system.set_pump(None)
        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
