"""What the user hears when Gachashift itself fails or a run was cut off."""

import copy
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from gachashift import __main__ as cli
from gachashift import report as R
from gachashift import runner
from gachashift.config import DEFAULT_CONFIG


class UnfinishedRunTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        path = pathlib.Path(self.folder.name) / "running.json"
        last = pathlib.Path(self.folder.name) / "last_run.json"
        self.patches = [mock.patch.object(runner, "running_file", lambda: path),
                        mock.patch.object(runner, "last_results_file", lambda: last)]
        for patch in self.patches:
            patch.start()
        self.path = path

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.folder.cleanup()

    def test_no_file(self):
        self.assertIsNone(runner.unfinished_run())

    def test_process_gone(self):
        self.path.write_text(json.dumps({"pid": 999999999, "started": "07:00:00"}))
        os.utime(self.path, (1795129200, 1795129200))
        self.assertRegex(runner.unfinished_run() or "", r"^\d\d-\d\d \d\d:\d\d$")

    def test_process_still_running(self):
        self.path.write_text(json.dumps({"pid": os.getpid(), "started": "07:00:00"}))
        self.assertIsNone(runner.unfinished_run())

    def test_note_comes_before_the_games(self):
        self.path.write_text(json.dumps({"pid": 999999999, "started": "07:00:00"}))
        game = R.GameReport("zzz")
        game.add("邮件", R.OK)
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        with mock.patch.object(runner, "run_games", lambda *a, **k: ([game], False)), \
                mock.patch.object(runner, "wait_for_unlock", lambda: True), \
                mock.patch.object(runner, "clear_stop", lambda: None):
            reports = runner.run_all(cfg, allow_shutdown=False, send=False, log=lambda m: None)
        self.assertEqual([r.game for r in reports], ["system", "zzz"])
        self.assertEqual(reports[0].notes[0][0], "note.previous_unfinished")
        self.assertFalse(self.path.exists())  # this run finished, so its own file is gone


class CrashMessageTest(unittest.TestCase):
    def cfg(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["report_language"] = "zh"
        cfg["telegram"] = {"enabled": True, "bot_token": "TOKEN", "chat_id": "42"}
        cfg["discord"] = {"enabled": True, "webhook_url": "https://discord.example/hook"}
        return cfg

    def run_main(self, argv, error):
        def crash(*args, **kwargs):
            raise error

        with mock.patch.object(sys, "argv", ["gachashift", *argv]), \
                mock.patch.object(cli, "start_run_log", lambda: None), \
                mock.patch.object(cli, "load_config", self.cfg), \
                mock.patch.object(cli, "run_all", crash), \
                mock.patch.object(R.requests, "post") as post, \
                mock.patch("traceback.print_exc"):
            with self.assertRaises(SystemExit):
                cli.main()
        return post

    def test_scheduled_run_crash_is_sent(self):
        post = self.run_main([], RuntimeError("boom"))
        urls = [call.args[0] for call in post.call_args_list]
        self.assertEqual(urls, ["https://api.telegram.org/botTOKEN/sendMessage",
                                "https://discord.example/hook"])
        text = post.call_args_list[0].kwargs["json"]["text"]
        self.assertIn("RuntimeError: boom", text)
        self.assertIn("logs/gachashift_", text)

    def test_test_run_crash_is_not_sent(self):
        post = self.run_main(["--only", "zzz"], RuntimeError("boom"))
        post.assert_not_called()

    def test_send_never_raises(self):
        with mock.patch.object(R.requests, "post", side_effect=OSError("offline")):
            R.send_text(self.cfg(), "hello")  # must not raise while handling another error


if __name__ == "__main__":
    unittest.main()
