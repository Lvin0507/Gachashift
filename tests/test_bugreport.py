"""The problem report: what goes in, and that nothing private does."""

import copy
import json
import pathlib
import tempfile
import unittest
import zipfile
from unittest import mock

from gachashift import bugreport
from gachashift.config import DEFAULT_CONFIG

TOKEN = "1234567890:AAH9xv-Ab_cdEFghIJklMNopQRstUVwxyz12"
HOOK = "https://discord.com/api/webhooks/1199/abcDEF-ghi_JKL"


class RedactTest(unittest.TestCase):
    def setUp(self):
        cfg = {"telegram": {"bot_token": TOKEN, "chat_id": "987654321"},
               "discord": {"webhook_url": HOOK}}
        self.redact = bugreport.redactor(cfg, home=r"C:\Users\Alvin")

    def test_secrets(self):
        text = self.redact(f"token {TOKEN} chat 987654321 hook {HOOK}")
        for secret in (TOKEN, "987654321", HOOK):
            self.assertNotIn(secret, text)

    def test_any_telegram_token_or_webhook(self):
        other = "5555555555:BBH9xv-Ab_cdEFghIJklMNopQRstUVwxyz99"
        text = self.redact(f"{other} https://discordapp.com/api/webhooks/1/x")
        self.assertNotIn(other, text)
        self.assertNotIn("webhooks/1/x", text)

    def test_game_uid_everywhere_it_appears(self):
        line = '当前UID: "828785035"，识别值: "828785035"\n委托数据保存完成: "828785035"'
        self.assertNotIn("828785035", self.redact(line))

    def test_user_folder_sid_email(self):
        text = self.redact(r"C:\Users\Alvin\Downloads\MaaEnd.exe c:/users/alvin/x "
                           "BetterGI.v2.user-S-1-5-21-2261861509-1912837125-3848909809-1001.root "
                           "mail me@example.com")
        self.assertNotIn("Alvin", text.replace("%USERPROFILE%", ""))
        self.assertNotIn("alvin", text)
        self.assertIn(r"%USERPROFILE%\Downloads\MaaEnd.exe", text)
        self.assertNotIn("2261861509", text)
        self.assertNotIn("me@example.com", text)

    def test_ordinary_text_kept(self):
        self.assertEqual(self.redact("当前每日委托奖励进度: 3/4"), "当前每日委托奖励进度: 3/4")


class BuildTest(unittest.TestCase):
    def test_zip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            home, app = root / "Users" / "Alvin", root / "app"
            (home / "Desktop").mkdir(parents=True)
            logs = app / "logs"
            (logs / "screens").mkdir(parents=True)
            (logs / "gachashift_2026-11-24.log").write_text(
                f"[07:00:01] starting {home}\\Downloads\\MaaEnd.exe\nTelegram {TOKEN}\n", encoding="utf-8")
            (logs / "screens" / "2026-11-24_070500_wuthering.jpg").write_bytes(b"jpg")
            okww = root / "okww.log"
            okww.write_text("乐园任务完成\n" * 10, encoding="utf-8")
            cfg = copy.deepcopy(DEFAULT_CONFIG)
            cfg["telegram"] = {"enabled": True, "bot_token": TOKEN, "chat_id": "987654321"}
            cfg["discord"] = {"enabled": True, "webhook_url": HOOK}
            cfg["games"]["wuthering"].update(enabled=True, log_path=str(okww))
            with mock.patch.object(bugreport, "app_dir", lambda: app):
                path = bugreport.build(cfg, home=str(home))
            self.assertEqual(path.parent, home / "Desktop")
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
                everything = "".join(z.read(n).decode("utf-8", "replace") for n in names if not n.endswith(".jpg"))
                settings = json.loads(z.read("settings.json"))
        self.assertEqual(names, {"about.txt", "settings.json", "logs/gachashift_2026-11-24.log",
                                 "screens/2026-11-24_070500_wuthering.jpg", "tools/wuthering-ok-script.log"})
        for secret in (TOKEN, HOOK, "987654321", "Alvin"):
            self.assertNotIn(secret, everything)
        self.assertEqual(settings["telegram"]["bot_token"], "(removed)")
        self.assertIn("乐园任务完成", everything)


if __name__ == "__main__":
    unittest.main()
