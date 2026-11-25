"""Change a tool's own setting to what Gachashift relies on, for the problems toolcheck finds.

Only settings that are a plain switch or value are changed; anything that needs a choice
(which of several accounts, a whole new task) is left to the player. A tool writes its
settings back when it closes, so nothing is changed while the tool is open. The file is
copied to <name>.gachashift-backup first, and written in the same layout it had."""

import json
import os
import random
import re
import shutil
import string

from . import toolcheck as C
from .system import process_running, processes_in

BACKUP = ".gachashift-backup"
BGI_CLOSE_BOTH = "关闭游戏和软件"
BAAS_EXIT = "退出 Baas"


class FixError(Exception):
    """Why a setting couldn't be changed; the message is an i18n key."""


# --- reading and writing a file in its own layout ----------------------------------------

def load(path):
    """(data, layout) of a JSON file; layout remembers the BOM, line ends and indent."""
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    bom = text.startswith("﻿")
    body = text.lstrip("﻿")
    indent = re.search(r"\n( +)\S", body)
    layout = {"bom": bom, "crlf": "\r\n" in body, "indent": len(indent.group(1)) if indent else 2,
              "trailing": body.endswith("\n")}
    return json.loads(body), layout


def save_text(path, text):
    shutil.copy2(path, path + BACKUP)
    temp = path + ".gachashift-new"
    with open(temp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(temp, path)


def save(path, data, layout):
    text = json.dumps(data, ensure_ascii=False, indent=layout["indent"])
    if layout["trailing"]:
        text += "\n"
    if layout["crlf"]:
        text = text.replace("\n", "\r\n")
    if layout["bom"]:
        text = "﻿" + text
    save_text(path, text)


def edit(path, change):
    """Load a JSON file, let `change` modify it in place, then write it back."""
    if not path or not os.path.isfile(path):
        raise FixError("fix.no_file")
    data, layout = load(path)
    change(data)
    save(path, data, layout)


def need_game_path(game_cfg):
    path = game_cfg.get("game_path") or ""
    if not os.path.isfile(path):
        raise FixError("fix.need_game_path")
    return path


# --- MaaEnd -------------------------------------------------------------------------------

def _task_id():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(7))


def _full_run(instance):
    """True for a config that opens the game first and closes it last (a whole morning)."""
    tasks = [t for t in instance.get("tasks") or [] if t.get("enabled", True)]
    return bool(tasks) and "LaunchGame" in tasks[0].get("taskName", "") \
        and tasks[-1].get("taskName") == "__MXU_KILLPROC__"


def maaend_autorun(data, game_cfg):
    settings = data.setdefault("settings", {})
    instances = data.get("instances") or []
    ids = [i.get("id") for i in instances]
    if settings.get("autoStartInstanceId") not in ids:
        # which config runs is the player's choice; pick one only when it is clear
        full = [i.get("id") for i in instances if _full_run(i)]
        if len(full) == 1:
            settings["autoStartInstanceId"] = full[0]
        elif len(ids) == 1:
            settings["autoStartInstanceId"] = ids[0]
        else:
            raise FixError("fix.choose_in_tool")
    settings["autoRunOnLaunch"] = True


def maaend_close(data, game_cfg):
    instance = C.maaend_instance(data)
    if instance is None:
        raise FixError("fix.choose_in_tool")
    tasks = instance.setdefault("tasks", [])
    kill = next((t for t in tasks if t.get("taskName") == "__MXU_KILLPROC__" and t.get("enabled", True)), None)
    if kill is None:
        controller = instance.get("controllerName") or "Win32-Front"
        kill = {"enabled": True, "enabledByController": {controller: True}, "expanded": False,
                "id": _task_id(), "optionValues": {
                    "__MXU_KILLPROC_NAME_OPTION__": {"type": "input", "values": {"process_name": "Endfield.exe"}}},
                "taskName": "__MXU_KILLPROC__"}
    else:
        tasks.remove(kill)  # anything after it would run with the game already closed
    kill.setdefault("optionValues", {})["__MXU_KILLPROC_SELF_OPTION__"] = {"type": "switch", "value": True}
    tasks.append(kill)


def maaend_power(data, game_cfg):
    instance = C.maaend_instance(data)
    if instance is None:
        raise FixError("fix.choose_in_tool")
    for task in instance.get("tasks") or []:
        if task.get("taskName") == "__MXU_POWER__":
            task["enabled"] = False
            for controller in task.get("enabledByController") or {}:
                task["enabledByController"][controller] = False


# --- MAA ----------------------------------------------------------------------------------

def _maa_gui(data):
    current = C.maa_current(data)
    if current is None:
        raise FixError("fix.choose_in_tool")
    return current, current.setdefault("Gui", {})


def maa_pc(data, game_cfg):
    _maa_gui(data)[1].setdefault("ConnectSettings", {})["Config"] = "PC"


def maa_autorun(data, game_cfg):
    _maa_gui(data)[1].setdefault("StartUpSettings", {})["RunDirectly"] = True


def maa_client(data, game_cfg):
    start = _maa_gui(data)[1].setdefault("StartUpSettings", {})
    if not C._exists(start.get("PcClientPath")):
        start["PcClientPath"] = need_game_path(game_cfg)
    start["StartPcClient"] = True


def maa_startup(data, game_cfg):
    current = _maa_gui(data)[0]
    task = next((t for t in current.get("TaskQueue") or [] if t.get("TaskType") == "StartUp"), None)
    if task is None:
        raise FixError("fix.choose_in_tool")
    task["IsEnable"] = True


def maa_power(data, game_cfg):
    _maa_gui(data)[1]["PostActions"] = "None"


# --- the rest -----------------------------------------------------------------------------

def okww_path(game_cfg):
    path = need_game_path(game_cfg)
    edit(os.path.join(C.okww_config_dir(game_cfg) or "", "devices.json"),
         lambda data: data.__setitem__("pc_full_path", path))


def okww_autostart(game_cfg):
    edit(os.path.join(C.okww_config_dir(game_cfg) or "", "Basic Options.json"),
         lambda data: data.__setitem__("Auto Start Game When App Starts", True))


def baas_each_running(game_cfg, change):
    paths = C.baas_config_paths(game_cfg)
    running = [p for p, d in paths.items() if d.get("autostart") is True]
    if not running:
        raise FixError("fix.no_file")
    for path in running:
        edit(path, change)


def baas_autostart(game_cfg):
    paths = list(C.baas_config_paths(game_cfg))
    if len(paths) != 1:
        raise FixError("fix.choose_in_tool")  # which server should run is the player's choice
    edit(paths[0], lambda data: data.__setitem__("autostart", True))


def baas_emulator(game_cfg):
    baas_each_running(game_cfg, lambda data: data.__setitem__("open_emulator_stat", False))


def baas_exit(game_cfg):
    baas_each_running(game_cfg, lambda data: data.__setitem__("then", BAAS_EXIT))


def onedragon_instance(game_cfg):
    path = C.onedragon_path(game_cfg)
    if not os.path.isfile(path):
        raise FixError("fix.no_file")
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()  # as it is, \r\n and all
    if len(re.findall(r"^-\s*idx:", text, re.M)) != 1:
        raise FixError("fix.choose_in_tool")  # which account joins is the player's choice
    new, count = re.subn(r"^(\s*active_in_od:\s*)false(\s*)$", r"\g<1>true\g<2>", text, flags=re.M | re.I)
    if count != 1:
        raise FixError("fix.choose_in_tool")
    save_text(path, new)


def bgi_game_path(game_cfg):
    path = need_game_path(game_cfg)
    config = (C.bgi_paths(game_cfg) or ("",))[0]
    edit(config, lambda data: data.setdefault("genshinStartConfig", {}).__setitem__("installPath", path))


def bgi_finish(game_cfg):
    flow = (C.bgi_paths(game_cfg) or ("", "", ""))[2]

    def change(data):
        key = next((k for k in data if k.lower() == "completionaction"), "CompletionAction")
        data[key] = BGI_CLOSE_BOTH
    edit(flow, change)


def _json_fix(path_of, change):
    """A fix that changes one JSON file the tool keeps."""
    return lambda game_cfg: edit(path_of(game_cfg), lambda data: change(data, game_cfg))


FIXES = {
    ("endfield", "tool.maaend_autorun"): _json_fix(C.maaend_config_path, maaend_autorun),
    ("endfield", "tool.maaend_close"): _json_fix(C.maaend_config_path, maaend_close),
    ("endfield", "tool.power"): _json_fix(C.maaend_config_path, maaend_power),
    ("arknights", "tool.maa_pc"): _json_fix(C.maa_config_path, maa_pc),
    ("arknights", "tool.maa_autorun"): _json_fix(C.maa_config_path, maa_autorun),
    ("arknights", "tool.maa_client"): _json_fix(C.maa_config_path, maa_client),
    ("arknights", "tool.maa_startup"): _json_fix(C.maa_config_path, maa_startup),
    ("arknights", "tool.power"): _json_fix(C.maa_config_path, maa_power),
    ("wuthering", "tool.okww_path"): okww_path,
    ("wuthering", "tool.okww_autostart"): okww_autostart,
    ("bluearchive", "tool.baas_autostart"): baas_autostart,
    ("bluearchive", "tool.baas_emulator"): baas_emulator,
    ("bluearchive", "tool.baas_exit"): baas_exit,
    ("bluearchive", "tool.power"): baas_exit,
    ("zzz", "tool.od_instance"): onedragon_instance,
    ("genshin", "tool.bgi_game_path"): bgi_game_path,
    ("genshin", "tool.bgi_finish"): bgi_finish,
    ("genshin", "tool.power"): bgi_finish,
}


def can_fix(gid, key):
    return (gid, key) in FIXES


def tool_running(gid, game_cfg):
    """True while the game's tool is open (it would write its old settings back on closing)."""
    if gid == "endfield":
        return process_running("MaaEnd.exe")
    if gid == "arknights":
        return process_running("MAA.exe")
    if gid == "genshin":
        return process_running("BetterGI.exe")
    folder = {"wuthering": os.path.dirname(game_cfg.get("okww_path") or ""),
              "bluearchive": game_cfg.get("baas_dir"), "zzz": game_cfg.get("od_dir")}.get(gid)
    return bool(folder) and bool(processes_in(folder))


def fix(gid, key, game_cfg, running=tool_running):
    """Change the setting behind one problem. Returns None when done, or an i18n key saying
    why not."""
    if not can_fix(gid, key):
        return "fix.choose_in_tool"
    if running(gid, game_cfg):
        return "fix.tool_running"
    try:
        FIXES[(gid, key)](game_cfg)
    except FixError as e:
        return str(e)
    except (OSError, ValueError) as e:
        print(f"could not change {key} for {gid}: {type(e).__name__}: {e}")
        return "fix.failed"
    return None


# --- where each tool says the game is -----------------------------------------------------

def game_paths_from_tools(games_cfg):
    """{game id: game exe} read from the tools' own settings, for the paths that exist.
    These are the most reliable: the tool already starts the game from there."""
    found = {}

    def keep(gid, path):
        if C._exists(path) and os.path.isfile(path):
            found[gid] = os.path.normpath(path)

    def safe(read):
        try:
            return read()
        except Exception:
            return None

    endfield = games_cfg.get("endfield") or {}
    data = safe(lambda: C.maaend_config(endfield))
    if isinstance(data, dict):
        instance = C.maaend_instance(data) or {}
        keep("endfield", (instance.get("savedDevice") or {}).get("connectedProgramPath"))
    data = safe(lambda: C.maa_config(games_cfg.get("arknights") or {}))
    if isinstance(data, dict):
        current = C.maa_current(data) or {}
        keep("arknights", ((current.get("Gui") or {}).get("StartUpSettings") or {}).get("PcClientPath"))
    files = safe(lambda: C.okww_configs(games_cfg.get("wuthering") or {})) or {}
    keep("wuthering", (files.get("devices.json") or {}).get("pc_full_path"))
    files = safe(lambda: C.bgi_files(games_cfg.get("genshin") or {})) or {}
    keep("genshin", ((files.get("config") or {}).get("genshinStartConfig") or {}).get("installPath"))
    return found
