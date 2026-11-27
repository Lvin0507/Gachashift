"""Arknights: Endfield via MaaEnd. MaaEnd launches the game itself and exits when done."""

import datetime
import glob
import json
import re
import os
import shutil
import subprocess
import time

from .. import report as R
from ..config import app_dir
from ..system import (StopRequested, gryphlink_processes, kill, kill_processes, pause, process_running,
                      read_since, start_steam_elevated, ts)
from . import maaend_tasks
from .base import Game


def remove_file(path):
    try:
        os.remove(path)
    except OSError:
        pass

TASKS = ["LaunchGamePC", "StashBackpackMain", "DijiangRewards", "OutpostTradingSchedule",
         "AutoStockStapleSchedule", "AutoStockpileMain", "DeliveryJobsMain", "AutoSellMain",
         "EnvironmentMonitoringMain", "TrialOfSwordmancyMain", "SeizeDeliveryJobs",
         "VisitFriendsMain", "CreditShoppingMain", "GiftOperatorMain", "DailyRewardStart",
         "MXU_KILLPROC"]
ALIASES = {"SeizeDeliveryJobsMain": "SeizeDeliveryJobs",
           "SeizeDeliveryJobsCheckOngoingJob": "SeizeDeliveryJobs",
           "SellProductSchedule": "AutoSellMain",
           # MaaEnd renamed the stash task's entry (seen 26 Nov); both mean the same task
           "StashBackpackEntry": "StashBackpackMain"}
DELIVERY_TARGET = 3
# MaaEnd sometimes renames a task's entry, mostly by changing this last word
# (StashBackpackMain became StashBackpackEntry); names are compared without it
ENTRY_SUFFIX = re.compile(r"(Main|Entry|Start|Schedule|Task)$")


def base_name(entry):
    return ENTRY_SUFFIX.sub("", entry)


def match_renamed(runs, fails, expected):
    """Count a task under its expected name when the log only has a renamed entry for it, and
    return the expected tasks that didn't run while unknown ones did (perhaps renamed further)."""
    known_by_base = {base_name(k): k for k in expected}
    for key in [k for k in runs if k not in expected]:
        known = known_by_base.get(base_name(key))
        if known and not runs.get(known):
            runs[known] = runs.pop(key)
            fails[known] = fails.pop(key, 0)
    if not any(k not in expected for k in runs):
        return []
    return [k for k in expected if k != "LaunchGamePC" and not runs.get(k)]


class FailureWatch:
    """Reads go-service.log while MaaEnd runs, to take a picture as soon as a task fails.

    A task's first error line comes when it gets stuck (a target not found on screen); "Task
    failed" only comes once MaaEnd has given up on it, often after leaving that screen. So the
    picture is taken at the first error line and kept if the task then fails; a task that
    recovers from its error has its picture deleted. snap(key) takes the picture, returning
    its path; remove(path) deletes one."""

    def __init__(self, path, snap, remove, offset=0):
        self.path, self.snap, self.remove = path, snap, remove
        self.offset = offset
        self.current = None      # (task_id, key) of the task running now
        self.pending = {}        # task_id -> (key, path) taken at an error, not yet confirmed
        self.kept = []           # (key, path) of tasks that failed
        self.done = set()        # task ids with a kept picture

    def poll(self):
        text = read_since(self.path, self.offset)
        end = text.rfind("\n")
        if end < 0:
            return
        chunk = text[:end + 1]
        self.offset += len(chunk.encode("utf-8"))
        for raw in chunk.splitlines():
            self.line(raw.strip())

    def line(self, raw):
        if not raw.startswith("{"):
            return
        try:
            rec = json.loads(raw)
        except ValueError:
            return
        msg, entry, task_id = rec.get("message", ""), rec.get("entry"), rec.get("task_id")
        if entry and task_id is not None and msg == "Checking aspect ratio before task execution":
            self.finish_current()
            self.current = (task_id, ALIASES.get(entry, entry))
        elif entry and task_id is not None and "Task failed" in msg:
            self.failed(task_id, ALIASES.get(entry, entry))
        elif rec.get("level") == "error" and self.current:
            tid, key = self.current
            if tid not in self.pending and tid not in self.done:
                path = self.snap(key)
                if path:
                    self.pending[tid] = (key, path)

    def failed(self, task_id, key):
        if task_id in self.done:
            return
        shot = self.pending.pop(task_id, None)
        if shot is None:
            path = self.snap(key)
            shot = (key, path) if path else None
        if shot:
            self.kept.append(shot)
            self.done.add(task_id)

    def finish_current(self):
        """The task before the next one didn't fail after all: drop its picture."""
        if self.current:
            shot = self.pending.pop(self.current[0], None)
            if shot:
                self.remove(shot[1])

    def close(self):
        self.poll()
        self.finish_current()
        for key, path in self.pending.values():
            self.remove(path)
        self.pending = {}
        return self.kept


def parse_endfield_log(text, rep, interrupted=False, expected=None, labels=None):
    """Fill `rep` from MaaEnd's go-service.log (one JSON object per line).
    A run starts at "Checking aspect ratio before task execution"; any "Task failed" line
    marks it failed (some failures are only logged at debug level).
    expected: the entries the run should do, in order (from maaend_tasks.plan); without it,
    the fixed TASKS list. labels: MaaEnd's own names for them, used when ours has none."""
    expected = list(expected) if expected else TASKS
    rep.labels.update(labels or {})
    runs, fails = {}, {}
    launch = None
    deliveries = delivery_activity = 0
    current = None
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        msg = rec.get("message", "")
        if rec.get("task") == "LaunchGamePC":
            if msg == "Pretask succeeded":
                launch = True
            elif launch is None:
                launch = False
            continue
        entry = rec.get("entry")
        key = ALIASES.get(entry, entry)
        if entry and msg == "Checking aspect ratio before task execution":
            runs[key] = runs.get(key, 0) + 1
            current = key
        elif entry and "Task failed" in msg:
            fails[key] = fails.get(key, 0) + 1
        elif (current == "SeizeDeliveryJobs" and msg == "item quantity added from recognition"
              and rec.get("item_id") == "item_spaceship_credit"):
            deliveries += 1
        if current == "SeizeDeliveryJobs" and rec.get("component") in (
                "SeizeDeliveryJobs", "AutoDeliveryResolveDestinationAction"):
            delivery_activity += 1

    if launch is None and not runs:
        rep.note("note.no_records")
        return rep
    missing = match_renamed(runs, fails, expected)
    if "LaunchGamePC" in expected:  # not when the game is opened by a pre-action
        rep.add("LaunchGamePC", {True: R.OK, False: R.FAIL, None: R.SKIPPED}[launch])
    for key in expected:
        if key == "LaunchGamePC":
            continue
        n_runs, n_fails = runs.get(key, 0), fails.get(key, 0)
        if key == "SeizeDeliveryJobs" and n_runs:
            detail = f"{deliveries}/{DELIVERY_TARGET}"
            if n_fails:
                rep.add(key, R.FAIL, detail)
            elif deliveries >= DELIVERY_TARGET:
                rep.add(key, R.OK, detail)
            elif deliveries == 0 and delivery_activity == 0:
                rep.add(key, R.NOTHING)
            else:
                rep.add(key, R.PARTIAL, detail)
            continue
        if n_runs == 0:
            rep.add(key, R.SKIPPED)
        elif n_fails:
            rep.add(key, R.FAIL, f"{n_fails}/{n_runs}" if n_runs > 1 else "")
        else:
            rep.add(key, R.OK)
    unknown = [key for key in runs if key not in expected]
    for key in unknown:
        rep.add(key, R.FAIL if fails.get(key) else R.OK, new=True)
    if unknown and missing and not interrupted:
        # a task that "didn't run" next to a new one is most likely the same task renamed
        rep.note("note.maybe_renamed", new=", ".join(unknown))
    if interrupted and current:
        # the task that was running when the user stopped didn't get to finish
        for task in rep.tasks:
            if task.key == current and task.status != R.FAIL:
                task.status, task.detail = R.SKIPPED, ""
    return rep


def archive_log(log_dir, keep_days=14):
    """MaaEnd overwrites go-service.log on every launch, so keep a dated copy."""
    try:
        archive = app_dir() / "logs"
        archive.mkdir(exist_ok=True)
        src = os.path.join(log_dir, "go-service.log")
        if os.path.exists(src):
            stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
            shutil.copy2(src, archive / f"go-service_{stamp}.log")
        cutoff = time.time() - keep_days * 86400
        for f in glob.glob(str(archive / "go-service_*.log")):
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
    except OSError as e:
        print(f"log archive failed: {e}")


class Endfield(Game):
    id = "endfield"
    required = ("maaend_path", "log_dir")

    def game_exes(self):
        return ("Endfield.exe",)

    def launcher_running(self):
        return bool(gryphlink_processes())

    def launcher_key(self):
        return "endfield:gryphlink"

    def launcher_group(self):
        return "gryphlink"

    def launcher_screen(self):
        from ..updater import WindowsScreen
        return WindowsScreen(processes=gryphlink_processes, game_exes=self.game_exes())

    def steam_app(self):
        # MaaEnd's Steam option: found by the folder of the game's exe
        return (None, self.cfg.get("game_path") or "") if self.cfg.get("via_steam") else None

    def run(self, timeout=5400):
        path = self.cfg["maaend_path"]
        log = os.path.join(self.cfg["log_dir"], "go-service.log")
        stop = failures = None
        try:
            if self.cfg.get("via_steam"):
                # MaaEnd starts the game through Steam; a Steam without admin rights would make
                # the game ask for them, a prompt nobody is there to answer
                start_steam_elevated()
            # only what this run writes: an old log left behind mustn't trigger pictures
            log_start = os.path.getsize(log) if os.path.exists(log) else 0
            print(f"[{ts()}] starting {path}")
            subprocess.Popen([path], cwd=os.path.dirname(path))
            pause(15)
            start = time.time()
            watch = self.watch(log)
            failures = FailureWatch(log, self.snap, remove_file, log_start) if self.shot_dir else None
            rounds = 0
            while process_running("MaaEnd.exe") and time.time() - start < timeout:
                # every 2 s for the failure pictures; the rest every 10 s as before
                pause(2)
                rounds += 1
                if failures:
                    failures.poll()
                if rounds % 5:
                    continue
                if self.stuck(watch):
                    break
                # MaaEnd stays open after its launch step fails; don't wait out the whole timeout
                if "failed to run launcher pipeline" in read_since(log, 0):
                    print(f"[{ts()}] MaaEnd could not start the game; stopping it")
                    break
        except StopRequested as e:
            stop = e
        finally:
            if failures:
                self.failure_shots = failures.close()
            self.capture(["MaaEnd.exe", "Endfield.exe"])
            kill(["MaaEnd.exe", "Endfield.exe"])
            kill_processes(gryphlink_processes())
            time.sleep(5)
            archive_log(self.cfg["log_dir"])
        expected, labels = maaend_tasks.plan(self.cfg, ALIASES)
        rep = parse_endfield_log(read_since(log, 0), self.new_report(), interrupted=bool(stop),
                                 expected=expected, labels=labels)
        if stop:
            stop.report = rep  # show what was finished before the stop
            raise stop
        return rep
