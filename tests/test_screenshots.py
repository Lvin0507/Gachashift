"""When a screenshot is taken, which ones are sent, and how they are sent."""

import pathlib
import tempfile
import unittest
from unittest import mock

from gachashift import report as R
from gachashift import runner
from gachashift.games import base
from gachashift.games.base import Game


class Fake(Game):
    id = "wuthering"


class CaptureTest(unittest.TestCase):
    def capture(self, running, shot_dir="shots"):
        game = Fake({})
        game.shot_dir = shot_dir
        with mock.patch.object(base, "process_running", lambda name: name in running), \
                mock.patch.object(base, "processes_in", lambda folder: []), \
                mock.patch.object(base, "capture_screen", lambda path: path):
            game.capture(["Client-Win64-Shipping.exe", None])
        return game.shot

    def test_game_still_open(self):
        shot = self.capture({"Client-Win64-Shipping.exe"})
        self.assertRegex(shot, r"shots[\\/]\d{4}-\d\d-\d\d_\d{6}_wuthering\.jpg$")

    def test_everything_already_closed(self):
        # the tool closed the game itself: the picture would only show the desktop
        self.assertIsNone(self.capture(set()))

    def test_switched_off(self):
        self.assertIsNone(self.capture({"Client-Win64-Shipping.exe"}, shot_dir=None))


class RunGameTest(unittest.TestCase):
    def test_picture_travels_with_the_report(self):
        class Shoots(Game):
            id = "zzz"

            def run(self):
                self.shot = "screen.jpg"
                rep = self.new_report()
                rep.add("邮件", R.FAIL)
                return rep

        rep = runner.run_game(Shoots, {}, "en", wait_reset=False, shots="shots")
        self.assertEqual(rep.screenshot, "screen.jpg")

    def test_picture_kept_when_the_game_crashes(self):
        class Crashes(Game):
            id = "zzz"

            def run(self):
                self.shot = "screen.jpg"
                raise OSError("disk full")

        rep = runner.run_game(Crashes, {}, "en", wait_reset=False, shots="shots")
        self.assertEqual(rep.screenshot, "screen.jpg")


class WhichToSendTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.folder.cleanup()

    def report(self, game, status):
        path = pathlib.Path(self.folder.name) / f"{game}.jpg"
        path.write_bytes(b"jpg")
        rep = R.GameReport(game)
        rep.add("task", status)
        rep.screenshot = str(path)
        return rep

    def test_only_the_bad_ones(self):
        good, bad = self.report("zzz", R.OK), self.report("wuthering", R.FAIL)
        photos = runner.screenshots_to_send([good, bad], stopped=False, lang="zh")
        self.assertEqual(photos, [("鸣潮：Gachashift 关掉前的屏幕", bad.screenshot)])
        self.assertFalse(pathlib.Path(self.folder.name, "zzz.jpg").exists())
        self.assertTrue(pathlib.Path(bad.screenshot).exists())

    def test_none_after_a_stop(self):
        bad = self.report("wuthering", R.FAIL)
        self.assertEqual(runner.screenshots_to_send([bad], stopped=True, lang="en"), [])
        self.assertFalse(pathlib.Path(self.folder.name, "wuthering.jpg").exists())


class SendTest(unittest.TestCase):
    def test_telegram_and_discord(self):
        cfg = {"telegram": {"enabled": True, "bot_token": "TOKEN", "chat_id": "42"},
               "discord": {"enabled": True, "webhook_url": "https://discord.example/hook"}}
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "shot.jpg"
            path.write_bytes(b"jpg")
            with mock.patch.object(R.requests, "post") as post:
                R.send_photos(cfg, [("caption", str(path))])
        telegram, discord = post.call_args_list
        self.assertEqual(telegram.args[0], "https://api.telegram.org/botTOKEN/sendPhoto")
        self.assertEqual(telegram.kwargs["data"], {"chat_id": "42", "caption": "caption"})
        self.assertIn("photo", telegram.kwargs["files"])
        self.assertEqual(discord.args[0], "https://discord.example/hook")
        self.assertEqual(discord.kwargs["files"]["file"][0], "shot.jpg")

    def test_send_never_raises(self):
        cfg = {"telegram": {"enabled": True, "bot_token": "T", "chat_id": "1"}}
        R.send_photos(cfg, [("caption", "/no/such/file.jpg")])  # must not raise


if __name__ == "__main__":
    unittest.main()
