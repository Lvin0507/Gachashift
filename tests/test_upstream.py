"""The upstream watch list covers what the parsers read, and finds a missing string."""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from gachashift.games import arknights, genshin, wuthering

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_upstream", ROOT / "tools" / "check_upstream.py")
check_upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_upstream)


def watched(repo):
    return next(e["strings"] for e in check_upstream.WATCH if e["repo"] == repo)


class WatchListTest(unittest.TestCase):
    def test_maa_strings_are_watched(self):
        strings = watched("MaaAssistantArknights/MaaAssistantArknights")
        for group in (arknights.DONE_MARKERS, arknights.START_WORDS, arknights.COMPLETE_WORDS,
                      arknights.RECRUIT_CONFIRM, arknights.RECRUIT_TASK):
            for s in group:
                self.assertIn(s, strings)

    def test_okww_strings_are_watched(self):
        strings = watched("ok-oldking/ok-wuthering-waves")
        for s in wuthering.DONE + wuthering.CURRENT:
            self.assertIn(s, strings)
        self.assertIn(wuthering.FAILED, watched("ok-oldking/ok-script"))

    def test_bettergi_strings_are_watched(self):
        strings = watched("babalae/better-genshin-impact")
        for s in (genshin.CLAIMED, genshin.DONE):
            self.assertIn(s, strings)

    def test_every_entry_is_complete(self):
        for entry in check_upstream.WATCH:
            self.assertTrue(entry["paths"] and entry["strings"], entry["repo"])
            self.assertTrue((ROOT / entry["used_in"]).is_file(), entry["used_in"])


class CheckTest(unittest.TestCase):
    def fake_fetch(self, files):
        def fetch(repo, paths, dest):
            if repo not in files:
                raise subprocess.CalledProcessError(128, "git", stderr="fatal: repository not found\n")
            os.makedirs(dest)
            for name, text in files[repo].items():
                with open(os.path.join(dest, name), "w", encoding="utf-8") as f:
                    f.write(text)
        return fetch

    def test_missing_and_unreachable(self):
        watch = [{"repo": "a/a", "game": "A", "used_in": "x", "paths": ["p"], "strings": ["kept", "gone"]},
                 {"repo": "b/b", "game": "B", "used_in": "x", "paths": ["p"], "strings": ["ok"]},
                 {"repo": "c/c", "game": "C", "used_in": "x", "paths": ["p"], "strings": ["ok"]}]
        fetch = self.fake_fetch({"a/a": {"one.cs": 'Log("kept")'}, "b/b": {"two.po": "ok"}})
        problems = check_upstream.check(watch, fetch)
        self.assertEqual([(e["repo"], missing, error) for e, missing, error in problems],
                         [("a/a", ["gone"], None), ("c/c", [], "fatal: repository not found")])
        text = check_upstream.report(problems)
        self.assertIn("- [ ] `gone`", text)
        self.assertIn("repository not found", text)

    def test_found_across_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "sub"))
            Path(tmp, "a.txt").write_text("first", encoding="utf-8")
            Path(tmp, "sub", "b.txt").write_text("second", encoding="utf-8")
            self.assertEqual(check_upstream.missing_in(tmp, ["first", "second", "third"]), ["third"])


if __name__ == "__main__":
    unittest.main()
