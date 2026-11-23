"""The Windows settings check, with powercfg output in English and Chinese."""

import unittest

from gachashift import health

SLEEP_EN = """Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  Subgroup GUID: 238c9fa8-0aad-41ed-83f4-97be242c8f20  (Sleep)
    Power Setting GUID: 29f6c1db-86da-48c5-9fdb-f2b67b1f44da  (Sleep after)
      Minimum Possible Setting: 0x00000000
      Maximum Possible Setting: 0xffffffff
      Possible Settings increment: 0x00000001
      Possible Settings units: Seconds
    Current AC Power Setting Index: 0x00000708
    Current DC Power Setting Index: 0x00000384
"""

LID_ZH = """电源方案 GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (平衡)
  子组 GUID: 4f971e89-eebd-4455-a8de-9e59040e7347  (电源按钮和盖子)
    电源设置 GUID: 5ca83367-6e45-459f-a27b-476b1d01c936  (合上盖子操作)
      可能的设置索引: 000
      可能的设置友好名称: 不采取任何操作
      可能的设置索引: 001
      可能的设置友好名称: 睡眠
    当前交流电源设置索引: 0x00000001
    当前直流电源设置索引: 0x00000001
"""


class ValuesTest(unittest.TestCase):
    def test_english(self):
        self.assertEqual(health.setting_values(SLEEP_EN), (1800, 900))

    def test_chinese(self):
        self.assertEqual(health.setting_values(LID_ZH), (1, 1))

    def test_nothing(self):
        self.assertIsNone(health.setting_values("The system cannot find the file specified."))


class CheckTest(unittest.TestCase):
    def run_check(self, values, lid=False, saver=False):
        return [p.key for p in health.check(query=lambda sub, s: values.get(s), has_lid=lambda: lid,
                                            secure_screen_saver=lambda: saver)]

    def test_all_good(self):
        self.assertEqual(self.run_check({"CONSOLELOCK": (1, 1), "STANDBYIDLE": (0, 900),
                                         "HIBERNATEIDLE": (0, 0), "LIDACTION": (0, 1)}, lid=True), [])

    def test_sleep_with_password(self):
        problems = health.check(query=lambda sub, s: {"CONSOLELOCK": (1, 1), "STANDBYIDLE": (1800, 900)}.get(s),
                                has_lid=lambda: False, secure_screen_saver=lambda: False)
        self.assertEqual([(p.key, p.params) for p in problems], [("health.sleep", {"minutes": 30})])

    def test_sleep_without_password_is_fine(self):
        # the schedule wakes the PC, and with no password it goes straight to the desktop
        self.assertEqual(self.run_check({"CONSOLELOCK": (0, 1), "STANDBYIDLE": (1800, 900)}), [])

    def test_unknown_password_setting_counts_as_asking(self):
        self.assertEqual(self.run_check({"STANDBYIDLE": (600, 0)}), ["health.sleep"])

    def test_lid_and_screen_saver(self):
        self.assertEqual(self.run_check({"CONSOLELOCK": (1, 1), "LIDACTION": (1, 1)}, lid=True, saver=True),
                         ["health.screen_saver", "health.lid"])

    def test_desktop_has_no_lid(self):
        self.assertEqual(self.run_check({"LIDACTION": (1, 1)}, lid=False), [])


if __name__ == "__main__":
    unittest.main()
