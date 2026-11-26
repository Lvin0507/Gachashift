"""Reading the tasks a run should do from MaaEnd's own files (interface.json, its imports,
its translations and the config it runs on launch)."""

import json
import os
import tempfile
import unittest

from gachashift import report as R
from gachashift.games import maaend_tasks
from gachashift.games.endfield import ALIASES, parse_endfield_log

# The way MaaEnd writes these files: comments and trailing commas included
STASH = """{
    "task": [
        {
            "name": "StashBackpack",
            "label": "$task.StashBackpack.label",
            "entry": "StashBackpackEntry", // renamed from StashBackpackMain
            "controller": [
                "Win32-Front",
                // "CloudWeb",
            ],
        },
    ],
}"""
SELL = '{"task": [{"name": "SellProduct", "entry": "OutpostTradingSchedule"}]}'
GIFT = '{"task": [{"name": "GiftOperator", "entry": "GiftOperatorMain"}]}'
SEIZE = '{"task": [{"name": "SeizeDeliveryJobs", "entry": "SeizeDeliveryJobsCheckOngoingJob"}]}'
WAR = '{"task": [{"name": "WarEcho", "entry": "WarEchoEntry"}]}'
INTERFACE = """{
    "interface_version": 2,
    /* tasks live in the imported files */
    "task": [],
    "import": ["tasks/StashBackpack.json", "tasks/OutpostTrading.json", "tasks/GiftOperator.json",
               "tasks/SeizeDeliveryJobs.json", "tasks/WarEcho.json", "tasks/Missing.json"],
}"""
ZH = {"task.StashBackpack.label": "🎒存放背包", "task.WarEcho.label": "⚔️战争回响"}
EN = {"task.StashBackpack.label": "🎒Stash Backpack", "task.WarEcho.label": "⚔️ War Echo"}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text if isinstance(text, str) else json.dumps(text, ensure_ascii=False))


def task(name, enabled=True, **extra):
    return dict({"taskName": name, "enabled": enabled, "optionValues": {}}, **extra)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = self.tmp.name
        write(os.path.join(root, "interface.json"), INTERFACE)
        for name, text in (("StashBackpack", STASH), ("OutpostTrading", SELL), ("GiftOperator", GIFT),
                           ("SeizeDeliveryJobs", SEIZE), ("WarEcho", WAR)):
            write(os.path.join(root, "tasks", name + ".json"), text)
        write(os.path.join(root, "locales", "interface", "zh_cn.json"), ZH)
        write(os.path.join(root, "locales", "interface", "en_us.json"), EN)
        self.cfg = {"maaend_path": os.path.join(root, "MaaEnd.exe")}

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, tasks, pre_actions=None):
        instance = {"id": "a1", "tasks": tasks}
        if pre_actions:
            instance["preActions"] = pre_actions
        write(os.path.join(self.root, "config", "mxu-MaaEnd.json"),
              {"instances": [instance], "settings": {"autoRunOnLaunch": True, "autoStartInstanceId": "a1"}})

    def test_plan_follows_the_config(self):
        self.config([task("__MXU_PRETASK__LaunchGamePC"), task("StashBackpack"),
                     task("GiftOperator", enabled=False), task("SellProduct"),
                     task("SellProduct", customName="🛒售卖产品（武陵）"), task("__MXU_SLEEP__"),
                     task("SeizeDeliveryJobs"), task("TaskMaaEndRemoved"), task("__MXU_KILLPROC__")])
        entries, labels = maaend_tasks.plan(self.cfg, ALIASES)
        # renamed entries come out under the names our labels know (ALIASES)
        self.assertEqual(entries, ["LaunchGamePC", "StashBackpackMain", "OutpostTradingSchedule",
                                   "SeizeDeliveryJobs", "MXU_KILLPROC"])
        self.assertEqual(labels["StashBackpackMain"], {"zh": "存放背包", "en": "Stash Backpack"})

    def test_report_from_the_plan(self):
        self.config([task("StashBackpack"), task("GiftOperator", enabled=False), task("WarEcho"),
                     task("__MXU_KILLPROC__")],
                    pre_actions=[{"enabled": True, "program": "D:/Game/Endfield.exe"}])
        entries, labels = maaend_tasks.plan(self.cfg, ALIASES)
        start = "Checking aspect ratio before task execution"
        log = "\n".join(json.dumps(r) for r in (
            {"entry": "StashBackpackEntry", "message": start},
            {"entry": "WarEchoEntry", "message": start},
            {"entry": "MXU_KILLPROC", "message": start}))
        rep = parse_endfield_log(log, R.GameReport("endfield"), expected=entries, labels=labels)
        # no launch row (a pre-action opens the game), nothing about the gift task that's off
        self.assertEqual([(t.key, t.status) for t in rep.tasks],
                         [("StashBackpackMain", R.OK), ("WarEchoEntry", R.OK), ("MXU_KILLPROC", R.OK)])
        self.assertEqual(R.outcome(rep), "ok")
        self.assertEqual(rep.label("StashBackpackMain", "en"), "Stash backpack")  # our own name first
        self.assertEqual(rep.label("WarEchoEntry", "zh"), "战争回响")  # MaaEnd's, emoji left out
        self.assertEqual(rep.label("WarEchoEntry", "en"), "War Echo")

    def test_unreadable_files_fall_back(self):
        self.assertEqual(maaend_tasks.plan({"maaend_path": ""}), (None, {}))
        self.config([task("StashBackpack")])
        os.remove(os.path.join(self.root, "interface.json"))
        self.assertEqual(maaend_tasks.plan(self.cfg), (None, {}))


class JsoncTest(unittest.TestCase):
    def test_comments_and_commas(self):
        text = '{"a": "http://x // not a comment", /* gone */ "b": [1, 2,], // end\n}'
        self.assertEqual(json.loads(maaend_tasks.strip_jsonc(text)), {"a": "http://x // not a comment", "b": [1, 2]})

    def test_escaped_quote(self):
        text = '{"a": "say \\"hi\\" // still text",}'
        self.assertEqual(json.loads(maaend_tasks.strip_jsonc(text)), {"a": 'say "hi" // still text'})


if __name__ == "__main__":
    unittest.main()
