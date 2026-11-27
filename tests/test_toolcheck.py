"""The tool settings check, with trimmed copies of each tool's real config files."""

import json
import os
import tempfile
import unittest
from unittest import mock

from gachashift import report as R
from gachashift import runner, toolcheck


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))


def maaend(tasks, autorun=True, pre_actions=None):
    instance = {"id": "a1", "name": "Full daily", "tasks": tasks}
    if pre_actions is not None:
        instance["preActions"] = pre_actions
    return {"instances": [{"id": "other", "tasks": []}, instance],
            "lastActiveInstanceId": "a1",
            "settings": {"autoRunOnLaunch": autorun, "autoStartInstanceId": "a1"}}


LAUNCH = {"enabled": True, "taskName": "__MXU_PRETASK__LaunchGamePC", "optionValues": {}}
DAILY = {"enabled": True, "taskName": "DailyRewards", "optionValues": {}}
KILL = {"enabled": True, "taskName": "__MXU_KILLPROC__", "optionValues": {
    "__MXU_KILLPROC_NAME_OPTION__": {"type": "input", "values": {"process_name": "Endfield.exe"}},
    "__MXU_KILLPROC_SELF_OPTION__": {"type": "switch", "value": True}}}
POWER = {"enabled": True, "taskName": "__MXU_POWER__",
         "optionValues": {"__MXU_POWER_OPTION__": {"caseName": "sleep", "type": "select"}}}


class MaaEndTest(unittest.TestCase):
    def test_good(self):
        self.assertEqual(toolcheck.check_maaend(maaend([LAUNCH, DAILY, KILL])), [])

    def test_disabled_tasks_dont_count(self):
        off = dict(DAILY, enabled=False)
        self.assertEqual(toolcheck.check_maaend(maaend([LAUNCH, DAILY, KILL, off])), [])

    def test_launch_by_pre_action(self):
        pre = [{"enabled": True, "program": "D:\\Game\\Endfield.exe"}]
        self.assertEqual(toolcheck.check_maaend(maaend([DAILY, KILL], pre_actions=pre)), [])

    def test_no_launch(self):
        self.assertEqual(toolcheck.check_maaend(maaend([DAILY, KILL])), ["tool.maaend_launch"])

    def test_not_closing_itself(self):
        keep_open = json.loads(json.dumps(KILL))
        keep_open["optionValues"]["__MXU_KILLPROC_SELF_OPTION__"]["value"] = False
        self.assertEqual(toolcheck.check_maaend(maaend([LAUNCH, DAILY, keep_open])), ["tool.maaend_close"])
        self.assertEqual(toolcheck.check_maaend(maaend([LAUNCH, DAILY])), ["tool.maaend_close"])

    def test_sleep_and_no_autorun(self):
        self.assertEqual(toolcheck.check_maaend(maaend([LAUNCH, DAILY, KILL, POWER], autorun=False)),
                         ["tool.maaend_autorun", "tool.maaend_close", "tool.power"])

    def test_no_config_chosen_to_run(self):
        # what MaaEnd writes when "run on launch" is set to nothing (seen 25 Nov)
        data = maaend([LAUNCH, DAILY, KILL])
        data["settings"]["autoStartInstanceId"] = None
        self.assertEqual(toolcheck.check_maaend(data), ["tool.maaend_autorun"])
        del data["settings"]["autoStartInstanceId"]
        self.assertEqual(toolcheck.check_maaend(data), ["tool.maaend_autorun"])

    def test_deleted_config_chosen_to_run(self):
        # the tasks of a config that no longer exists aren't checked, but nothing would run
        data = maaend([DAILY])
        data["settings"]["autoStartInstanceId"] = "gone"
        data["lastActiveInstanceId"] = "gone"
        self.assertEqual(toolcheck.check_maaend(data), ["tool.maaend_autorun"])

    def test_not_a_config(self):
        self.assertEqual(toolcheck.check_maaend(None), [])
        self.assertEqual(toolcheck.check_maaend([]), [])


def maa(connect="PC", run_directly=True, start_client=True, client="C:\\AK\\Arknights.exe",
        startup=True, post="None"):
    return {"Current": "Default", "Configurations": {"Default": {
        "TaskQueue": [{"$type": "StartUpTask", "TaskType": "StartUp", "IsEnable": startup},
                      {"$type": "AwardTask", "TaskType": "Award", "IsEnable": True}],
        "Gui": {"ConnectSettings": {"Config": connect},
                "StartUpSettings": {"RunDirectly": run_directly, "StartPcClient": start_client,
                                    "PcClientPath": client},
                "PostActions": post}}}}


def always(path):
    return True


class MaaTest(unittest.TestCase):
    def check(self, data, exists=always):
        return toolcheck.check_maa(data, exists=exists)

    def test_good(self):
        self.assertEqual(self.check(maa()), [])

    def test_emulator(self):
        self.assertEqual(self.check(maa(connect="MuMuEmulator12")), ["tool.maa_pc"])

    def test_no_autorun(self):
        self.assertEqual(self.check(maa(run_directly=False)), ["tool.maa_autorun"])

    def test_client(self):
        self.assertEqual(self.check(maa(start_client=False)), ["tool.maa_client"])
        self.assertEqual(self.check(maa(), exists=lambda p: False), ["tool.maa_client"])

    def test_startup_task_off(self):
        self.assertEqual(self.check(maa(startup=False)), ["tool.maa_startup"])

    def test_power(self):
        self.assertEqual(self.check(maa(post="ExitArknights, Hibernate")), ["tool.power"])

    def test_other_shapes(self):
        self.assertEqual(self.check({"Configurations": {}}), [])
        self.assertEqual(self.check(None), [])


class OkwwTest(unittest.TestCase):
    def files(self, path="D:\\WW\\Client-Win64-Shipping.exe", autostart=True):
        return {"devices.json": {"preferred": "pc_1", "pc_full_path": path, "capture": "WGC"},
                "Basic Options.json": {"Auto Start Game When App Starts": autostart}}

    def test_good(self):
        self.assertEqual(toolcheck.check_okww(self.files(), exists=always), [])

    def test_no_path_and_no_autostart(self):
        self.assertEqual(toolcheck.check_okww(self.files("", False), exists=bool),
                         ["tool.okww_path", "tool.okww_autostart"])

    def test_steam_starts_the_game_itself(self):
        self.assertEqual(toolcheck.check_okww(self.files("", False), steam_client=True, exists=bool), [])

    def test_reads_configs_beside_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            working = os.path.join(tmp, "data", "apps", "ok-ww", "working")
            write(os.path.join(working, "configs", "Basic Options.json"),
                  {"Auto Start Game When App Starts": False})
            cfg = {"log_path": os.path.join(working, "logs", "ok-script.log")}
            self.assertEqual(toolcheck.check_game("wuthering", cfg), ["tool.okww_autostart"])


def baas(**changes):
    config = {"name": "server", "autostart": True, "then": "退出 Baas",
              "open_emulator_stat": False, "server": "日服PC端"}
    config.update(changes)
    return config


class BaasTest(unittest.TestCase):
    def test_good(self):
        self.assertEqual(toolcheck.check_baas([baas()]), [])
        self.assertEqual(toolcheck.check_baas([baas(then="Exit Baas")]), [])

    def test_no_autostart(self):
        self.assertEqual(toolcheck.check_baas([baas(autostart=False)]), ["tool.baas_autostart"])

    def test_emulator_and_staying_open(self):
        self.assertEqual(toolcheck.check_baas([baas(open_emulator_stat=True, then="无动作")]),
                         ["tool.baas_emulator", "tool.baas_exit"])

    def test_shutdown(self):
        self.assertEqual(toolcheck.check_baas([baas(then="关机")]), ["tool.power"])

    def test_reads_config_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(os.path.join(tmp, "config", "1708232489", "config.json"), baas(autostart=False))
            write(os.path.join(tmp, "config", "1708232489", "switch.json"), [{"config": "cafeInvite"}])
            write(os.path.join(tmp, "config", "gui.json"), {"MainWindow": {}})
            self.assertEqual(toolcheck.check_game("bluearchive", {"baas_dir": tmp}), ["tool.baas_autostart"])


ONE_DRAGON = """instance_list:\r
- idx: 1\r
  name: '01'\r
  active: true\r
  active_in_od: {od}\r
  force_login_before_run: false\r
"""


class OneDragonTest(unittest.TestCase):
    def test_active(self):
        self.assertEqual(toolcheck.check_onedragon(ONE_DRAGON.format(od="true")), [])

    def test_not_in_one_dragon(self):
        self.assertEqual(toolcheck.check_onedragon(ONE_DRAGON.format(od="false")), ["tool.od_instance"])

    def test_missing_file(self):
        self.assertEqual(toolcheck.check_onedragon(None), [])
        self.assertEqual(toolcheck.check_game("zzz", {"od_dir": "/nowhere"}), [])


class BetterGITest(unittest.TestCase):
    def files(self, path="D:\\Genshin\\GenshinImpact.exe", flows=True, action="关闭游戏和软件"):
        flow = None if action is None else {"Name": "默认配置", "TaskOrder": [], "CompletionAction": action}
        return {"config": {"genshinStartConfig": {"installPath": path, "autoEnterGameEnabled": True}},
                "flows": flows, "flow": flow}

    def test_good(self):
        self.assertEqual(toolcheck.check_bgi(self.files(), exists=always), [])

    def test_game_path(self):
        self.assertEqual(toolcheck.check_bgi(self.files(path=""), exists=bool), ["tool.bgi_game_path"])

    def test_missing_flow(self):
        self.assertEqual(toolcheck.check_bgi(self.files(action=None), exists=always), ["tool.bgi_config"])
        # no OneDragon folder at all: a layout we don't know, so no warning
        self.assertEqual(toolcheck.check_bgi(self.files(flows=False, action=None), exists=always), [])

    def test_finish_action(self):
        self.assertEqual(toolcheck.check_bgi(self.files(action="关闭游戏"), exists=always), ["tool.bgi_finish"])
        self.assertEqual(toolcheck.check_bgi(self.files(action="关机"), exists=always), ["tool.power"])
        # a config added in BetterGI starts with no finishing action at all
        self.assertEqual(toolcheck.check_bgi(self.files(action=""), exists=always), ["tool.bgi_finish"])

    def test_reads_user_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(os.path.join(tmp, "User", "config.json"), {"genshinStartConfig": {"installPath": ""}})
            os.makedirs(os.path.join(tmp, "User", "OneDragon"))
            cfg = {"bgi_path": os.path.join(tmp, "BetterGI.exe"), "onedragon_config": "默认配置"}
            self.assertEqual(toolcheck.check_game("genshin", cfg), ["tool.bgi_game_path", "tool.bgi_config"])


class BetterGIConfigListTest(unittest.TestCase):
    def test_lists_the_one_dragon_configs(self):
        with tempfile.TemporaryDirectory() as folder:
            flows = os.path.join(folder, "User", "OneDragon")
            os.makedirs(os.path.join(flows, "backup.json"))   # a folder, not a config
            for name in ("默认配置.json", "只刷树脂.json", "notes.txt"):
                with open(os.path.join(flows, name), "w", encoding="utf-8") as f:
                    f.write("{}")
            self.assertEqual(toolcheck.bgi_flow_names(os.path.join(folder, "BetterGI.exe")),
                             ["只刷树脂", "默认配置"])

    def test_no_bettergi_yet(self):
        self.assertEqual(toolcheck.bgi_flow_names(""), [])
        self.assertEqual(toolcheck.bgi_flow_names("C:/nowhere/BetterGI.exe"), [])


class WholeCheckTest(unittest.TestCase):
    def test_only_games_that_are_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(os.path.join(tmp, "config", "one_dragon.yml"), ONE_DRAGON.format(od="false"))
            cfg = {"games": {"zzz": {"enabled": True, "od_dir": tmp},
                             "genshin": {"enabled": False, "bgi_path": os.path.join(tmp, "x.exe")}}}
            problems = toolcheck.check(cfg)
            self.assertEqual([(p.game, p.key) for p in problems], [("zzz", "tool.od_instance")])

    def test_a_broken_check_says_nothing(self):
        with mock.patch.object(toolcheck, "onedragon_file", side_effect=RuntimeError("boom")):
            self.assertEqual(toolcheck.check_game("zzz", {"od_dir": "x"}), [])

    def test_messages_exist(self):
        from gachashift.i18n import STRINGS
        keys = {k for k in STRINGS["en"] if k.startswith("tool.")}
        self.assertEqual(keys, {k for k in STRINGS["zh"] if k.startswith("tool.")})
        self.assertIn("tool.power", keys)


class ReportTest(unittest.TestCase):
    def test_failed_game_says_why(self):
        rep = R.GameReport("zzz")
        rep.add("一条龙", R.FAIL)
        with mock.patch.object(toolcheck, "check_game", return_value=["tool.od_instance"]):
            runner.explain(rep, {})
        self.assertIn(("tool.od_instance", {}), rep.notes)

    def test_good_game_is_left_alone(self):
        rep = R.GameReport("zzz")
        rep.add("一条龙", R.OK)
        with mock.patch.object(toolcheck, "check_game") as check:
            runner.explain(rep, {})
        check.assert_not_called()
        self.assertEqual(rep.notes, [])


if __name__ == "__main__":
    unittest.main()
