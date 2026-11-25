"""Fixing a tool's own settings: each change, the file layout kept, a backup, and the cases
that are left to the player."""

import json
import os
import tempfile
import unittest

from gachashift import finder, toolcheck, toolfix


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def dump(data, indent=2, crlf=False):
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    return text.replace("\n", "\r\n") if crlf else text


def not_running(gid, cfg):
    return False


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.game = os.path.join(self.root, "Game", "Game.exe")
        write(self.game, "")

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def fix(self, gid, key, cfg):
        return toolfix.fix(gid, key, cfg, running=not_running)


KILL_SELF_OFF = {"enabled": True, "taskName": "__MXU_KILLPROC__", "optionValues": {
    "__MXU_KILLPROC_NAME_OPTION__": {"type": "input", "values": {"process_name": "Endfield.exe"}},
    "__MXU_KILLPROC_SELF_OPTION__": {"type": "switch", "value": False}}}


class MaaEndFixTest(Base):
    def setup_maaend(self, tasks, autorun=False):
        data = {"instances": [{"id": "a1", "controllerName": "Win32-Front", "tasks": tasks,
                               "savedDevice": {"connectedProgramPath": self.game}}],
                "lastActiveInstanceId": "a1", "settings": {"autoRunOnLaunch": autorun, "autoStartInstanceId": "a1"},
                "version": "1.0"}
        file = self.path("MaaEnd", "config", "mxu-MaaEnd.json")
        write(file, dump(data))
        return {"maaend_path": self.path("MaaEnd", "MaaEnd.exe")}, file

    def test_autorun_and_close(self):
        launch = {"enabled": True, "taskName": "__MXU_PRETASK__LaunchGamePC"}
        daily = {"enabled": True, "taskName": "DailyRewards"}
        power = {"enabled": True, "taskName": "__MXU_POWER__", "enabledByController": {"Win32-Front": True}}
        cfg, file = self.setup_maaend([launch, dict(KILL_SELF_OFF), daily, power])
        self.assertEqual(toolcheck.check_game("endfield", cfg),
                         ["tool.maaend_autorun", "tool.maaend_close", "tool.power"])
        for key in toolcheck.check_game("endfield", cfg):
            self.assertIsNone(self.fix("endfield", key, cfg), key)
        self.assertEqual(toolcheck.check_game("endfield", cfg), [])
        tasks = json.loads(read(file))["instances"][0]["tasks"]
        # the kill task moved to the end, so the dailies after it still run with the game open
        self.assertEqual([t["taskName"] for t in tasks],
                         ["__MXU_PRETASK__LaunchGamePC", "DailyRewards", "__MXU_POWER__", "__MXU_KILLPROC__"])
        self.assertTrue(os.path.exists(file + toolfix.BACKUP))

    def test_choose_the_config_to_run(self):
        full = [{"enabled": True, "taskName": "__MXU_PRETASK__LaunchGamePC"}, dict(KILL_SELF_OFF)]
        full[1]["optionValues"]["__MXU_KILLPROC_SELF_OPTION__"] = {"type": "switch", "value": True}
        cfg, file = self.setup_maaend(full, autorun=True)
        data = json.loads(read(file))
        data["settings"]["autoStartInstanceId"] = None  # "run nothing on launch"
        data["instances"].append({"id": "t2", "name": "test", "tasks": [{"enabled": True, "taskName": "DailyRewards"}]})
        write(file, dump(data))
        self.assertEqual(toolcheck.check_game("endfield", cfg), ["tool.maaend_autorun"])
        self.assertIsNone(self.fix("endfield", "tool.maaend_autorun", cfg))
        # the one config that opens and closes the game is the morning run
        self.assertEqual(json.loads(read(file))["settings"]["autoStartInstanceId"], "a1")
        self.assertEqual(toolcheck.check_game("endfield", cfg), [])

    def test_main_config_not_first(self):
        # the morning config is second in the list and opens the game with a pre-action
        cfg, file = self.setup_maaend([{"enabled": True, "taskName": "DailyRewards"}], autorun=True)
        data = json.loads(read(file))
        data["settings"]["autoStartInstanceId"] = None
        data["instances"].append({"id": "main", "preActions": [{"enabled": True, "program": self.game}],
                                  "tasks": [{"enabled": True, "taskName": "DailyRewards"},
                                            {"enabled": True, "taskName": "__MXU_KILLPROC__"}]})
        write(file, dump(data))
        self.assertIsNone(self.fix("endfield", "tool.maaend_autorun", cfg))
        self.assertEqual(json.loads(read(file))["settings"]["autoStartInstanceId"], "main")

    def test_two_full_configs_is_a_choice(self):
        full = [{"enabled": True, "taskName": "__MXU_PRETASK__LaunchGamePC"},
                {"enabled": True, "taskName": "__MXU_KILLPROC__"}]
        cfg, file = self.setup_maaend(full, autorun=True)
        data = json.loads(read(file))
        data["settings"]["autoStartInstanceId"] = None
        data["instances"].append({"id": "t2", "tasks": list(full)})
        write(file, dump(data))
        self.assertEqual(self.fix("endfield", "tool.maaend_autorun", cfg), "fix.choose_in_tool")

    def test_adds_a_kill_task(self):
        cfg, file = self.setup_maaend([{"enabled": True, "taskName": "__MXU_PRETASK__LaunchGamePC"}], autorun=True)
        self.assertIsNone(self.fix("endfield", "tool.maaend_close", cfg))
        last = json.loads(read(file))["instances"][0]["tasks"][-1]
        self.assertEqual(last["taskName"], "__MXU_KILLPROC__")
        self.assertEqual(last["enabledByController"], {"Win32-Front": True})
        self.assertEqual(toolcheck.check_game("endfield", cfg), [])

    def test_launch_task_is_left_to_the_player(self):
        cfg, _ = self.setup_maaend([], autorun=True)
        self.assertFalse(toolfix.can_fix("endfield", "tool.maaend_launch"))
        self.assertEqual(self.fix("endfield", "tool.maaend_launch", cfg), "fix.choose_in_tool")

    def test_game_path_from_maaend(self):
        cfg, _ = self.setup_maaend([])
        self.assertEqual(toolfix.game_paths_from_tools({"endfield": cfg}),
                         {"endfield": os.path.normpath(self.game)})


class MaaFixTest(Base):
    def setup_maa(self, **gui):
        start = {"RunDirectly": False, "StartPcClient": False, "PcClientPath": ""}
        data = {"Configurations": {"Default": {
            "TaskQueue": [{"$type": "StartUpTask", "TaskType": "StartUp", "IsEnable": False}],
            "Gui": {"ConnectSettings": {"Config": "MuMuEmulator12"}, "StartUpSettings": start,
                    "PostActions": "Hibernate"}}}, "Current": "Default"}
        file = self.path("MAA", "config", "gui.new.json")
        write(file, "\ufeff" + dump(data, crlf=True) + "\r\n")
        return {"maa_path": self.path("MAA", "MAA.exe"), **gui}, file

    def test_everything(self):
        cfg, file = self.setup_maa(game_path=self.game)
        keys = toolcheck.check_game("arknights", cfg)
        self.assertEqual(keys, ["tool.maa_pc", "tool.maa_autorun", "tool.maa_startup", "tool.power"])
        for key in keys:
            self.assertIsNone(self.fix("arknights", key, cfg), key)
        # now connected to the PC client, so the client settings count too
        self.assertEqual(toolcheck.check_game("arknights", cfg), ["tool.maa_client"])
        self.assertIsNone(self.fix("arknights", "tool.maa_client", cfg))
        self.assertEqual(toolcheck.check_game("arknights", cfg), [])
        text = read(file)
        self.assertTrue(text.startswith("\ufeff{\r\n  \"Configurations\""))  # same layout as before
        self.assertTrue(text.endswith("}\r\n"))
        start = json.loads(text.lstrip("\ufeff"))["Configurations"]["Default"]["Gui"]["StartUpSettings"]
        self.assertEqual(start["PcClientPath"], self.game)

    def test_client_needs_the_game_path(self):
        cfg, _ = self.setup_maa()
        self.assertIsNone(self.fix("arknights", "tool.maa_pc", cfg))
        self.assertEqual(self.fix("arknights", "tool.maa_client", cfg), "fix.need_game_path")

    def test_tool_open(self):
        cfg, file = self.setup_maa()
        before = read(file)
        self.assertEqual(toolfix.fix("arknights", "tool.maa_pc", cfg, running=lambda g, c: True),
                         "fix.tool_running")
        self.assertEqual(read(file), before)


class OkwwFixTest(Base):
    def test_path_and_autostart(self):
        working = self.path("ok-ww", "data", "apps", "ok-ww", "working")
        write(os.path.join(working, "configs", "devices.json"), dump({"pc_full_path": "", "capture": "WGC"}, 4))
        write(os.path.join(working, "configs", "Basic Options.json"),
              dump({"Auto Start Game When App Starts": False}, 4, crlf=True))
        cfg = {"log_path": os.path.join(working, "logs", "ok-script.log"), "game_path": self.game}
        keys = toolcheck.check_game("wuthering", cfg)
        self.assertEqual(keys, ["tool.okww_path", "tool.okww_autostart"])
        for key in keys:
            self.assertIsNone(self.fix("wuthering", key, cfg), key)
        self.assertEqual(toolcheck.check_game("wuthering", cfg), [])
        self.assertIn('\r\n    "Auto Start', read(os.path.join(working, "configs", "Basic Options.json")))


class BaasFixTest(Base):
    def config(self, name, **values):
        data = {"name": name, "autostart": False, "then": "无动作", "open_emulator_stat": True}
        data.update(values)
        write(self.path("BAAS", "config", name, "config.json"), dump(data, 4))

    def test_one_server(self):
        self.config("1")
        cfg = {"baas_dir": self.path("BAAS")}
        self.assertIsNone(self.fix("bluearchive", "tool.baas_autostart", cfg))
        for key in toolcheck.check_game("bluearchive", cfg):
            self.assertIsNone(self.fix("bluearchive", key, cfg), key)
        self.assertEqual(toolcheck.check_game("bluearchive", cfg), [])
        data = json.loads(read(self.path("BAAS", "config", "1", "config.json")))
        self.assertEqual(data["then"], "退出 Baas")

    def test_two_servers_is_a_choice(self):
        self.config("1")
        self.config("2")
        cfg = {"baas_dir": self.path("BAAS")}
        self.assertEqual(self.fix("bluearchive", "tool.baas_autostart", cfg), "fix.choose_in_tool")


class OneDragonFixTest(Base):
    YML = "instance_list:\r\n- idx: 1\r\n  name: '01'\r\n  active: true\r\n  active_in_od: false\r\n"

    def test_one_account(self):
        write(self.path("OD", "config", "one_dragon.yml"), self.YML)
        cfg = {"od_dir": self.path("OD")}
        self.assertIsNone(self.fix("zzz", "tool.od_instance", cfg))
        self.assertEqual(read(self.path("OD", "config", "one_dragon.yml")),
                         self.YML.replace("active_in_od: false", "active_in_od: true"))

    def test_two_accounts_is_a_choice(self):
        write(self.path("OD", "config", "one_dragon.yml"),
              self.YML + "- idx: 2\r\n  name: '02'\r\n  active_in_od: false\r\n")
        self.assertEqual(self.fix("zzz", "tool.od_instance", {"od_dir": self.path("OD")}), "fix.choose_in_tool")


class BetterGIFixTest(Base):
    def test_game_path_and_finish(self):
        write(self.path("BGI", "User", "config.json"), dump({"genshinStartConfig": {"installPath": "C:\\gone.exe"}}))
        write(self.path("BGI", "User", "OneDragon", "默认配置.json"),
              dump({"Name": "默认配置", "CompletionAction": "关闭游戏"}, crlf=True))
        cfg = {"bgi_path": self.path("BGI", "BetterGI.exe"), "onedragon_config": "默认配置", "game_path": self.game}
        keys = toolcheck.check_game("genshin", cfg)
        self.assertEqual(keys, ["tool.bgi_game_path", "tool.bgi_finish"])
        for key in keys:
            self.assertIsNone(self.fix("genshin", key, cfg), key)
        self.assertEqual(toolcheck.check_game("genshin", cfg), [])
        self.assertEqual(toolfix.game_paths_from_tools({"genshin": cfg}), {"genshin": os.path.normpath(self.game)})


class GamePathSearchTest(Base):
    def test_steam_library_and_deep_exe(self):
        lib = self.path("SteamLibrary")
        common = os.path.join(lib, "steamapps", "common")
        ww = os.path.join(common, "Wuthering Waves", "Wuthering Waves Game", "Client", "Binaries", "Win64",
                          "Client-Win64-Shipping.exe")
        zzz = os.path.join(common, "ZenlessZoneZero", "ZenlessZoneZero.exe")
        other = os.path.join(common, "Some Unreal Game", "Client", "Binaries", "Win64", "Client-Win64-Shipping.exe")
        for path in (ww, zzz, other):
            write(path, "")
        steam = self.path("Steam")
        write(os.path.join(steam, "steamapps", "libraryfolders.vdf"),
              '"libraryfolders"\n{\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' % lib.replace("\\", "\\\\"))
        libraries = finder.libraries_in(os.path.join(steam, "steamapps", "libraryfolders.vdf"), steam)
        self.assertEqual(libraries, [os.path.normpath(common)])
        roots = finder.search_roots(home=self.path("home"), drives=[], steam=libraries)
        found = finder.search(roots, processes=[])
        self.assertEqual(found[("wuthering", "game_path")], ww)
        self.assertEqual(found[("zzz", "game_path")], zzz)

    def test_running_game_needs_the_right_folder(self):
        found = finder.search([], processes=["D:/Other/Client/Binaries/Win64/Client-Win64-Shipping.exe",
                                             "D:/Wuthering Waves/Client/Binaries/Win64/Client-Win64-Shipping.exe"])
        self.assertEqual(found[("wuthering", "game_path")],
                         "D:/Wuthering Waves/Client/Binaries/Win64/Client-Win64-Shipping.exe")


if __name__ == "__main__":
    unittest.main()
