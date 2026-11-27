"""The tools' own settings that Gachashift relies on, read from their config files.

A tool set up differently from what Gachashift expects fails in ways that can take the next
games down with it: a tool that never starts its tasks, never exits, or puts the PC to sleep.
Each check reads only what it needs and says nothing when a file is missing or in a format it
doesn't know, so an unusual setup never gets a false warning."""

import glob
import json
import os
import re

from .health import Problem

# Words in a "when done" choice that end the whole night, not just the tool
POWER = re.compile(r"shutdown|shut down|sleep|hibernat|restart|关机|睡眠|休眠|重启|シャットダウン|スリープ",
                   re.I)


def read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _exists(path):
    return bool(path) and os.path.exists(path)


def first(paths):
    return next((p for p in paths if os.path.isfile(p)), None)


# --- Endfield (MaaEnd) --------------------------------------------------------------------

def maaend_config_path(cfg):
    folder = os.path.dirname(cfg.get("maaend_path") or "")
    if not folder:
        return None
    return first([os.path.join(folder, "config", "mxu-MaaEnd.json"),
                  os.path.join(folder, "mxu-MaaEnd.json")]
                 + sorted(glob.glob(os.path.join(folder, "config", "mxu-*.json"))))


def maaend_config(cfg):
    path = maaend_config_path(cfg)
    return read_json(path) if path else None


def maaend_instance(data):
    """The instance MaaEnd runs when it starts by itself, or None if that isn't clear."""
    settings = data.get("settings") or {}
    instances = data.get("instances") or []
    wanted = settings.get("autoStartInstanceId") or data.get("lastActiveInstanceId")
    instance = next((i for i in instances if i.get("id") == wanted), None)
    if instance is None and len(instances) == 1:
        instance = instances[0]
    return instance


def _switch_on(task, option):
    value = (task.get("optionValues") or {}).get(option) or {}
    return value.get("value") is True


def check_maaend(data):
    if not isinstance(data, dict):
        return []
    problems = []
    settings = data.get("settings") or {}
    # MaaEnd's "run on launch" is two settings: the switch, and which config to run. Choosing
    # not to run anything clears the config (autoStartInstanceId) and leaves the switch on.
    ids = {i.get("id") for i in data.get("instances") or []}
    if settings.get("autoRunOnLaunch") is False or (
            "autoRunOnLaunch" in settings and settings.get("autoStartInstanceId") not in ids):
        problems.append("tool.maaend_autorun")
    instance = maaend_instance(data)
    if instance is None:
        return problems
    tasks = [t for t in instance.get("tasks") or [] if t.get("enabled", True)]
    pre_launch = any(a.get("enabled", True) and a.get("program")
                     for a in instance.get("preActions") or [])
    if not pre_launch and not (tasks and "LaunchGame" in tasks[0].get("taskName", "")):
        problems.append("tool.maaend_launch")
    last = tasks[-1] if tasks else {}
    # Gachashift waits for MaaEnd to exit, so the last task must close MaaEnd itself too
    if last.get("taskName") != "__MXU_KILLPROC__" or not _switch_on(last, "__MXU_KILLPROC_SELF_OPTION__"):
        problems.append("tool.maaend_close")
    if any(t.get("taskName") == "__MXU_POWER__" for t in tasks):
        problems.append("tool.power")
    return problems


# --- Arknights (MAA) ----------------------------------------------------------------------

def maa_config_path(cfg):
    folder = os.path.dirname(cfg.get("maa_path") or "")
    path = os.path.join(folder, "config", "gui.new.json") if folder else ""
    return path if os.path.isfile(path) else None


def maa_config(cfg):
    path = maa_config_path(cfg)
    return read_json(path) if path else None


def maa_current(data):
    current = (data.get("Configurations") or {}).get(data.get("Current") or "Default")
    return current if isinstance(current, dict) else None


def check_maa(data, exists=_exists):
    """Only MAA's newer config format (gui.new.json) is read."""
    if not isinstance(data, dict):
        return []
    current = maa_current(data)
    if current is None:
        return []
    gui = current.get("Gui") or {}
    problems = []
    connect = (gui.get("ConnectSettings") or {}).get("Config")
    if connect and connect != "PC":
        problems.append("tool.maa_pc")
    start = gui.get("StartUpSettings") or {}
    if start.get("RunDirectly") is False:
        problems.append("tool.maa_autorun")
    if connect == "PC" and (start.get("StartPcClient") is False
                            or ("PcClientPath" in start and not exists(start.get("PcClientPath")))):
        problems.append("tool.maa_client")
    queue = current.get("TaskQueue")
    if isinstance(queue, list) and not any(
            t.get("TaskType") == "StartUp" and t.get("IsEnable", True) for t in queue):
        problems.append("tool.maa_startup")
    if POWER.search(str(gui.get("PostActions") or "")):
        problems.append("tool.power")
    return problems


# --- Wuthering Waves (ok-ww) --------------------------------------------------------------

def okww_config_dir(cfg):
    """ok-ww keeps its settings next to its logs: working/configs beside working/logs."""
    log = cfg.get("log_path") or ""
    folder = os.path.join(os.path.dirname(os.path.dirname(log)), "configs") if log else ""
    return folder if os.path.isdir(folder) else None


def okww_configs(cfg):
    folder = okww_config_dir(cfg)
    if not folder:
        return None
    return {name: read_json(os.path.join(folder, name))
            for name in ("devices.json", "Basic Options.json")}


def check_okww(files, steam_client=False, exists=_exists):
    if not files:
        return []
    problems = []
    # Through Steam, Gachashift starts the game itself; otherwise ok-ww has to
    if not steam_client:
        devices = files.get("devices.json")
        if isinstance(devices, dict) and not exists(devices.get("pc_full_path")):
            problems.append("tool.okww_path")
        basic = files.get("Basic Options.json")
        if isinstance(basic, dict) and basic.get("Auto Start Game When App Starts") is False:
            problems.append("tool.okww_autostart")
    return problems


# --- Blue Archive (BAAS) ------------------------------------------------------------------

def baas_config_paths(cfg):
    """{path: config} for each BAAS server config (the ones with an "autostart" setting)."""
    folder = cfg.get("baas_dir") or ""
    if not folder:
        return {}
    found = {p: read_json(p) for p in sorted(glob.glob(os.path.join(folder, "config", "*", "config.json")))}
    return {p: d for p, d in found.items() if isinstance(d, dict) and "autostart" in d}


def baas_configs(cfg):
    return list(baas_config_paths(cfg).values()) or None


def _exits_baas(then):
    text = str(then).lower()
    return "baas" in text and any(word in text for word in ("退出", "exit", "終了", "quit", "close"))


def check_baas(configs):
    if not configs:
        return []
    running = [c for c in configs if c.get("autostart") is True]
    if not running:
        return ["tool.baas_autostart"]
    problems = []
    if any(c.get("open_emulator_stat") is True for c in running):
        problems.append("tool.baas_emulator")
    thens = [c.get("then") for c in running if "then" in c]
    if any(POWER.search(str(then)) for then in thens):
        problems.append("tool.power")
    elif any(not _exits_baas(then) for then in thens):
        problems.append("tool.baas_exit")
    return problems


# --- Zenless Zone Zero (OneDragon) --------------------------------------------------------

def onedragon_path(cfg):
    folder = cfg.get("od_dir") or ""
    return os.path.join(folder, "config", "one_dragon.yml") if folder else ""


def onedragon_file(cfg):
    path = onedragon_path(cfg)
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.read()
    except OSError:
        return None


def check_onedragon(text):
    """`-o` runs the one-dragon list for every account instance marked for it."""
    if not text or "instance_list" not in text:
        return []
    if re.search(r"^\s*active_in_od:\s*true\s*$", text, re.M | re.I):
        return []
    return ["tool.od_instance"]


# --- Genshin (BetterGI) -------------------------------------------------------------------

def bgi_paths(cfg):
    """(BetterGI's config.json, the one-dragon folder, this config's file), or None."""
    folder = os.path.dirname(cfg.get("bgi_path") or "")
    if not folder:
        return None
    user = os.path.join(folder, "User")
    flows = os.path.join(user, "OneDragon")
    name = cfg.get("onedragon_config") or "默认配置"
    return os.path.join(user, "config.json"), flows, os.path.join(flows, name + ".json")


def bgi_flow_names(bgi_path):
    """Names of the one-dragon configs in BetterGI (User/OneDragon/<name>.json), sorted."""
    folder = os.path.join(os.path.dirname(bgi_path or ""), "User", "OneDragon")
    if not bgi_path or not os.path.isdir(folder):
        return []
    return sorted(name[:-5] for name in os.listdir(folder)
                  if name.lower().endswith(".json") and os.path.isfile(os.path.join(folder, name)))


def bgi_files(cfg):
    paths = bgi_paths(cfg)
    if not paths:
        return None
    config, flows, flow = paths
    return {"config": read_json(config), "flows": os.path.isdir(flows), "flow": read_json(flow)}


def _find_key(data, wanted):
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() == wanted:
                return value
            found = _find_key(value, wanted)
            if found is not None:
                return found
    return None


def check_bgi(files, exists=_exists):
    if not files:
        return []
    problems = []
    start = (files.get("config") or {}).get("genshinStartConfig") or {}
    if "installPath" in start and not exists(start.get("installPath")):
        problems.append("tool.bgi_game_path")
    if files.get("flows") and files.get("flow") is None:
        problems.append("tool.bgi_config")
    action = _find_key(files.get("flow"), "completionaction")
    if action is not None:
        text = str(action)
        if POWER.search(text):
            problems.append("tool.power")
        elif "软件" not in text and "software" not in text.lower() and "bettergi" not in text.lower():
            # Gachashift knows BetterGI is done when it exits
            problems.append("tool.bgi_finish")
    return problems


# ------------------------------------------------------------------------------------------

def check_game(gid, cfg):
    """Problem keys for one game's tool, from the settings in Gachashift's config."""
    try:
        if gid == "endfield":
            return check_maaend(maaend_config(cfg))
        if gid == "arknights":
            return check_maa(maa_config(cfg))
        if gid == "wuthering":
            return check_okww(okww_configs(cfg), bool(cfg.get("steam_client")))
        if gid == "bluearchive":
            return check_baas(baas_configs(cfg))
        if gid == "zzz":
            return check_onedragon(onedragon_file(cfg))
        if gid == "genshin":
            return check_bgi(bgi_files(cfg))
    except Exception as e:  # a check must never stop the app or a run
        print(f"tool settings check for {gid} failed: {e}")
    return []


def check(cfg):
    """Problems for every game that is turned on."""
    problems = []
    for gid, game_cfg in (cfg.get("games") or {}).items():
        if game_cfg.get("enabled"):
            problems += [Problem(key, game=gid) for key in check_game(gid, game_cfg)]
    return problems
