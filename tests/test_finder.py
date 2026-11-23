"""Finding the tools in a folder tree laid out like a real PC."""

import os
import pathlib
import tempfile
import time
import unittest

from gachashift import finder

# Where the tools really were on the author's PC (relative to a home folder and a D: drive)
LAYOUT = {
    "home/Downloads/MaaEnd-win-x86_64-v1.17.2/MaaEnd.exe": 100,
    "home/Downloads/MaaEnd-win-x86_64-v3.2.0/MaaEnd.exe": 200,        # the newer download
    "home/Downloads/BlueArchiveAutoScript_v1.4.3_win_x86_64_full_env/BlueArchiveAutoScript_v1.4.3_win_x86_64.exe": 100,
    "home/Downloads/BetterGI_v0.66.0/BetterGI/BetterGI.exe": 100,
    "D/Games/MAA-v5.23.2-win-x64/MAA.exe": 100,
    "D/ok-ww/ok-ww.exe": 100,
    "D/YostarGames/BlueArchive_JP_Gamelauncher/BlueArchive_JP_Gamelauncher.exe": 100,
    "D/zzzod/OneDragon-Launcher.exe": 100,
    "D/SteamLibrary/steamapps/common/x/MAA.exe": 999,                  # skipped folder
}


class FinderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        for rel, mtime in LAYOUT.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
            os.utime(path, (mtime, mtime))
        self.roots = finder.search_roots(home=self.root / "home", drives=[str(self.root / "D")])

    def tearDown(self):
        self.tmp.cleanup()

    def p(self, rel):
        return str(self.root / rel)

    def test_finds_every_tool(self):
        found = finder.search(self.roots, processes=[])
        self.assertEqual(found, {
            ("endfield", "maaend_path"): self.p("home/Downloads/MaaEnd-win-x86_64-v3.2.0/MaaEnd.exe"),
            ("arknights", "maa_path"): self.p("D/Games/MAA-v5.23.2-win-x64/MAA.exe"),
            ("wuthering", "okww_path"): self.p("D/ok-ww/ok-ww.exe"),
            ("bluearchive", "baas_exe"): self.p("home/Downloads/BlueArchiveAutoScript_v1.4.3_win_x86_64_full_env/BlueArchiveAutoScript_v1.4.3_win_x86_64.exe"),
            ("bluearchive", "launcher_path"): self.p("D/YostarGames/BlueArchive_JP_Gamelauncher/BlueArchive_JP_Gamelauncher.exe"),
            ("zzz", "od_dir"): self.p("D/zzzod/OneDragon-Launcher.exe"),
            ("genshin", "bgi_path"): self.p("home/Downloads/BetterGI_v0.66.0/BetterGI/BetterGI.exe"),
        })

    def test_running_tool_wins(self):
        running = self.p("home/Downloads/MaaEnd-win-x86_64-v1.17.2/MaaEnd.exe")
        found = finder.search(self.roots, processes=[running, "C:/Windows/explorer.exe"])
        self.assertEqual(found[("endfield", "maaend_path")], running)

    def test_settings_that_follow(self):
        values = finder.settings_from(finder.search(self.roots, processes=[]))
        maa = self.p("D/Games/MAA-v5.23.2-win-x64")
        self.assertEqual(values["arknights"]["maa_log"], os.path.join(maa, "debug", "gui.log"))
        self.assertEqual(values["zzz"], {"od_dir": self.p("D/zzzod")})
        self.assertEqual(values["bluearchive"]["baas_dir"],
                         self.p("home/Downloads/BlueArchiveAutoScript_v1.4.3_win_x86_64_full_env"))
        self.assertEqual(values["wuthering"]["log_path"], os.path.join(
            self.p("D/ok-ww"), "data", "apps", "ok-ww", "working", "logs", "ok-script.log"))

    def test_only_empty_or_broken_settings_change(self):
        kept = self.p("D/ok-ww/ok-ww.exe")
        games = {"wuthering": {"okww_path": kept, "log_path": ""},
                 "arknights": {"maa_path": "C:/old/MAA.exe", "maa_log": "C:/old/debug/gui.log"},
                 "zzz": {"od_dir": ""}}
        found = {"wuthering": {"okww_path": "E:/other/ok-ww.exe", "log_path": "E:/other/log"},
                 "arknights": {"maa_path": "D:/MAA/MAA.exe", "maa_log": "D:/MAA/debug/gui.log"},
                 "genshin": {"bgi_path": "x"}}
        changed = finder.fill_missing(games, found)
        self.assertEqual(games["wuthering"]["okww_path"], kept)           # set and still there
        self.assertEqual(games["wuthering"]["log_path"], "E:/other/log")  # was empty
        self.assertEqual(games["arknights"]["maa_path"], "D:/MAA/MAA.exe")  # pointed nowhere
        self.assertEqual(changed, {"wuthering": ["log_path"], "arknights": ["maa_path", "maa_log"]})

    def test_time_limit(self):
        start = time.monotonic()
        finder.search(self.roots, time_limit=0, processes=[])
        self.assertLess(time.monotonic() - start, 1)


if __name__ == "__main__":
    unittest.main()
