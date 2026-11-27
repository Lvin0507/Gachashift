"""Genshin Impact via BetterGI's one-dragon run (一条龙).

`BetterGI.exe startOneDragon <config>` starts the game itself and runs the config's tasks.
Set the config's finishing action to close both the game and BetterGI: BetterGI exiting is
how we know the run is over. If that setting is off, the log's own end line is used instead.

BetterGI writes one log file per day, holding every run of that day, so only what was
written after we started counts."""

import datetime
import os
import re
import subprocess
import time

from .. import report as R
from ..system import StopRequested, kill, log_size, pause, process_running, read_since, ts
from .base import Game, minutes_since
from .zzz import SERVER_UTC

TOOL_EXE = "BetterGI.exe"
GAME_EXES = ["GenshinImpact.exe", "YuanShen.exe"]  # global / China client

# The log file quotes values ("全部领取"); BetterGI's console output doesn't. Accept both.
MAIL = re.compile(r"邮件：[\"“]?([^\"”\r\n]+)")
PROGRESS = re.compile(r"当前每日委托奖励进度: (\d+)/(\d+)")
SUCCESS_NAME = re.compile(r"委托执行成功：[\"“]?([^\"”\r\n]+)")
DISPATCH_CLAIMED = re.compile(r"探索派遣：[\"“]?全部领取")
DISPATCH_NOTHING = re.compile(r"探索派遣[\"”]? 未探索完成或已领取")
DAILY = re.compile(r"检查每日奖励结果：[\"“]?([^\"”\r\n]+)")
CLAIMED = "今日奖励已领取"
REWARD_TASK = "前往冒险家协会领取奖励"  # the one-dragon task that claims the commission reward
DONE = "一条龙和配置组任务结束"
# The commission script lists the four commissions it found ("委托 1 | name | 已完成 | ..."),
# which newer versions log even when they can't read the reward progress
LISTED = re.compile(r"^委托 (\d) \| .*? \| (已完成|未完成|未知) \|", re.M)
# Domains (自动秘境), which spend the resin
DOMAIN = re.compile(r"自动秘境任务：执行|自动秘境[\"”]?：")
# one domain reward claimed; older BetterGI: '"自动秘境"：使用 "原粹树脂", 数量：20',
# newer: '自动秘境：使用 原粹树脂，消耗：20'
DOMAIN_CLAIMED = re.compile(r"自动秘境[\"”]?：使用 [\"“]?[^\"”，,\r\n]+[\"”]?[,，] ?(?:数量|消耗)：\d+")
DOMAIN_ENDED = ("体力耗尽或者设置轮次已达标，结束自动秘境",  # resin used up, or the set rounds done
                "自动秘境：检测到树脂不足提示")             # no resin to start with


def log_path(bgi_dir, day):
    return os.path.join(bgi_dir, "log", f"better-genshin-impact{day:%Y%m%d}.log")


def count_commissions(text):
    """(done, total) of today's four commissions, or None if the script didn't run.
    The progress line is only logged when the commission page is read, usually before the
    commissions run, and the list of commissions likewise; the ones that finished after it
    are added."""
    succeeded = len(set(SUCCESS_NAME.findall(text)))
    found = []
    progress = PROGRESS.findall(text)
    if progress:
        first, total = int(progress[0][0]), int(progress[0][1])
        found.append((max(int(progress[-1][0]), min(total, first + succeeded)), total))
    starts = [m.start() for m in LISTED.finditer(text) if m.group(1) == "1"]
    if starts:
        # the last time the list was read, and what finished after it
        rest = text[starts[-1]:]
        listed = dict(LISTED.findall(rest))
        total = len(listed)
        before = sum(1 for state in listed.values() if state == "已完成")
        after = len(set(SUCCESS_NAME.findall(rest)))
        found.append((min(total, before + after), total))
    return max(found) if found else None


def parse_bgi_log(text, rep, minutes, reason, stopped=False):
    """Report the outcome of each step from the lines BetterGI writes when a step ends.
    The daily commission reward is the line that matters: it is claimed either by doing all
    four commissions or by spending Adventurer Rank points for the ones the script can't do."""
    if not text.strip():
        rep.note("note.no_records")
        return rep

    mail = MAIL.findall(text)
    if mail:
        rep.add("mail", R.OK)

    commissions = count_commissions(text)
    if commissions:
        done, total = commissions
        rep.add("commissions", R.OK if done == total else R.PARTIAL, f"{done}/{total}")

    if DISPATCH_CLAIMED.search(text):
        rep.add("dispatch", R.OK)
    elif DISPATCH_NOTHING.search(text):
        rep.add("dispatch", R.NOTHING)

    if DOMAIN.search(text):
        rounds = len(DOMAIN_CLAIMED.findall(text))
        if any(end in text for end in DOMAIN_ENDED):
            rep.add("domain", R.OK if rounds else R.NOTHING, f"×{rounds}" if rounds else "")
        elif stopped:
            rep.add("domain", R.SKIPPED)
        else:
            # BetterGI moved on without saying the resin was used up: an error or a wipe
            rep.add("domain", R.PARTIAL if rounds else R.FAIL, f"×{rounds}" if rounds else "")

    daily = DAILY.findall(text)
    if daily:
        result = daily[-1].strip()
        rep.add("daily_reward", R.OK if result == CLAIMED else R.FAIL,
                "" if result == CLAIMED else result)
    elif not (commissions or REWARD_TASK in text):
        pass  # a config without commissions (only domains, say): no reward to ask about
    elif stopped:
        rep.add("daily_reward", R.SKIPPED)
    else:
        rep.add("daily_reward", R.WARN)

    if stopped:
        return rep
    if DONE in text:
        rep.note("note.finished", minutes=minutes)
    else:
        rep.note("note.no_done_marker", reason=reason)
    return rep


class Genshin(Game):
    id = "genshin"
    required = ("bgi_path",)

    @property
    def reset(self):
        return (SERVER_UTC.get(self.cfg.get("server"), 8), 4)

    def run(self, start_timeout=180, timeout=3600):
        exe = self.cfg["bgi_path"]
        folder = os.path.dirname(exe)
        config = self.cfg.get("onedragon_config") or "默认配置"
        day = datetime.date.today()
        log = log_path(folder, day)
        # start clean, so the exit we wait for belongs to this run
        kill([TOOL_EXE, *GAME_EXES])
        offset = log_size(log)
        start, reason, saw_bgi, ended_at, stop = time.time(), "timeout", False, None, None
        try:
            print(f"[{ts()}] starting {exe} startOneDragon {config}")
            subprocess.Popen([exe, "startOneDragon", config], cwd=folder)
            watch = self.watch(log)
            while time.time() - start < timeout:
                pause(15)
                if self.stuck(watch):
                    reason = "stalled"
                    break
                if process_running(TOOL_EXE):
                    saw_bgi = True
                elif saw_bgi:
                    reason = "exited"  # the finishing action closed it: the run is over
                    break
                elif time.time() - start > start_timeout:
                    reason = "not_started"
                    break
                # if the finishing action isn't set, BetterGI stays open after its end line
                if ended_at is None and DONE in read_since(log, offset):
                    ended_at = time.time()
                if ended_at and time.time() - ended_at > 60:
                    reason = "done, left open"
                    break
        except StopRequested as e:
            stop, reason = e, "stopped"
        finally:
            self.capture([TOOL_EXE, *GAME_EXES])
            kill([TOOL_EXE, *GAME_EXES])
            time.sleep(3)
        print(f"[{ts()}] Genshin ended: {reason}")

        text = read_since(log, offset)
        today = datetime.date.today()
        if today != day:  # crossed midnight: the rest is in the next day's file
            text += "\n" + read_since(log_path(folder, today), 0)
        rep = self.new_report()
        if reason == "not_started":
            rep.add("daily_reward", R.FAIL)
            rep.note("note.not_started", hint="hint.bgi")
            return rep
        rep = parse_bgi_log(text, rep, minutes_since(start), reason, stopped=bool(stop))
        if stop:
            stop.report = rep
            raise stop
        return rep
