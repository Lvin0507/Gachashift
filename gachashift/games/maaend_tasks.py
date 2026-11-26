"""Which Endfield tasks a run should do, read from MaaEnd itself instead of a list kept here.

MaaEnd describes its tasks in interface.json and the files it imports (tasks/*.json): each
task has a name, the entry that shows up in its log, and a label in each language. The config
MaaEnd runs on launch lists the tasks the player turned on. Together they say what to expect
in the log, so a task MaaEnd renames or the player turns off is never reported as "not run".
Those files are JSON with comments and trailing commas, which are removed before parsing."""

import json
import os
import re

from .. import toolcheck

LAUNCH, CLOSE = "LaunchGamePC", "MXU_KILLPROC"
# A leading emoji in MaaEnd's labels ("🎁赠送礼物") is left out of the report
LEADING_SYMBOLS = re.compile(r"^[^\w぀-ヿ㐀-鿿]+")


def strip_jsonc(text):
    """JSON from JSON with // and /* */ comments and trailing commas."""
    out, i, n, in_string = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_jsonc(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.loads(strip_jsonc(f.read()))
    except (OSError, ValueError):
        return None


def interface_tasks(folder):
    """{task name: entry} from MaaEnd's interface.json and its imports, or None."""
    interface = load_jsonc(os.path.join(folder, "interface.json"))
    if not isinstance(interface, dict):
        return None
    tasks = list(interface.get("task") or [])
    for path in interface.get("import") or []:
        part = load_jsonc(os.path.join(folder, path))
        if isinstance(part, dict):
            tasks += part.get("task") or []
    found = {t["name"]: t["entry"] for t in tasks if isinstance(t, dict) and t.get("name") and t.get("entry")}
    return found or None


def task_labels(folder, interface):
    """{task name: {"zh": label, "en": label}} from MaaEnd's own translations."""
    labels = {}
    for lang, file in (("zh", "zh_cn.json"), ("en", "en_us.json")):
        texts = load_jsonc(os.path.join(folder, "locales", "interface", file)) or {}
        for name in interface:
            text = texts.get(f"task.{name}.label") if isinstance(texts, dict) else None
            if text:
                labels.setdefault(name, {})[lang] = LEADING_SYMBOLS.sub("", text).strip()
    return labels


def plan(cfg, aliases=None):
    """(entries in the order they run, {entry: {lang: label}}) for the config MaaEnd runs on
    launch, or (None, {}) when MaaEnd's files can't be read (the old fixed list is used)."""
    aliases = aliases or {}
    folder = os.path.dirname(cfg.get("maaend_path") or "")
    data = toolcheck.maaend_config(cfg)
    instance = toolcheck.maaend_instance(data) if isinstance(data, dict) else None
    interface = interface_tasks(folder) if folder else None
    if instance is None or interface is None:
        return None, {}
    names = task_labels(folder, interface)
    entries, labels = [], {}
    for task in instance.get("tasks") or []:
        if not task.get("enabled", True):
            continue
        name = task.get("taskName", "")
        if LAUNCH in name:
            entry = LAUNCH
        elif name == "__MXU_KILLPROC__":
            entry = CLOSE
        elif name.startswith("__MXU_"):
            continue  # MaaEnd's own steps (wait, sleep, power) leave no task record
        elif name in interface:
            entry = aliases.get(interface[name], interface[name])
            if name in names:
                labels[entry] = names[name]
        else:
            continue  # a task this MaaEnd no longer has; it can't run
        if entry not in entries:
            entries.append(entry)
    return entries, labels
