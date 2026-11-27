"""Check that the text Gachashift reads in each tool's log still exists in that tool's source.

Gachashift learns how a run went by finding certain lines in each tool's log. When a tool's
author rewords one of those lines, the morning report starts saying "please check" for a task
that actually went fine. This script looks for every such line in the tools' latest source on
GitHub, so a change is found the day it's published instead of the next time someone reads a
report closely. .github/workflows/upstream-watch.yml runs it every day and opens an issue.

Run it yourself with:  python tools/check_upstream.py
Exit code 0 means every string was found, 1 means something is missing or couldn't be checked.
Only the standard library is used, so it runs anywhere git is installed."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

# Each entry: the GitHub repo, the folders to download (kept small with a sparse checkout),
# what the strings are used for, and the exact text that must appear somewhere in those folders.
# When you change a parser, change its strings here too; tests/test_upstream.py checks that the
# parsers' own constants are listed.
WATCH = [
    {
        "repo": "MaaEnd/MaaEnd",
        "game": "Endfield",
        "used_in": "gachashift/games/endfield.py",
        "paths": ["agent/go-service", "assets/data/IconRecognition"],
        "strings": [
            "Checking aspect ratio before task execution",  # a task starts
            "Pretask succeeded",                            # the game was opened
            "Task failed",
            "failed to run launcher pipeline",              # the game could not be opened
            "item quantity added from recognition",         # delivery jobs taken
            "item_spaceship_credit",
            "AutoDeliveryResolveDestinationAction",
            '"SeizeDeliveryJobs"',
            "LaunchGamePC",
        ],
    },
    {
        "repo": "MaaAssistantArknights/MaaAssistantArknights",
        "game": "Arknights",
        "used_in": "gachashift/games/arknights.py",
        "paths": ["src/MaaWpfGui/Res/Localizations"],
        "strings": [
            # zh-CN
            "任务已全部完成", "开始任务:", "完成任务:", "已确认招募", "自动公招", "任务出错:",
            # zh-TW
            "任務已全部完成", "開始任務:", "完成任務:", "已確認招募", "自動公招", "任務出錯:",
            # en-US
            "All task(s) completed", "Start task:", "Complete task:", "Recruit confirm", "Auto Recruit",
            "Task error:",
            # ja-JP
            "すべてのタスクが完了しました", "タスク開始:", "タスク完了:", "募集を行いました", "公開求人",
            "タスクエラー:",
            # ko-KR
            "모든 작업을 완료했습니다", "작업 시작:", "작업 완료:", "모집 확정", "공개모집", "작업 오류:",
        ],
    },
    {
        "repo": "ok-oldking/ok-wuthering-waves",
        "game": "Wuthering Waves",
        "used_in": "gachashift/games/wuthering.py",
        "paths": ["i18n", "src/task"],
        "strings": [
            "Garden task completed", "Garden current: ",
            "乐园任务完成", "当前乐园进度：",
            "樂園任務完成", "當前樂園進度：",
            "楽園タスク完了", "現在の楽園進捗: ",
            "낙원 임무 완료", "현재 낙원 진행도: ",
            "Tarea del jardín completada", "Progreso actual del jardín: ",
        ],
    },
    {
        "repo": "ok-oldking/ok-script",
        "game": "Wuthering Waves",
        "used_in": "gachashift/games/wuthering.py",
        "paths": ["ok/task", "ok/device"],
        "strings": ["exception stopped", "game exited"],
    },
    {
        # BAAS keeps no log file; its scheduler file says which dailies got done
        "repo": "pur1fying/blue_archive_auto_script",
        "game": "Blue Archive",
        "used_in": "gachashift/games/bluearchive.py",
        "paths": ["core"],
        "strings": [
            '"/event.json"',
            "event['next_tick'] = int(event['next_tick'])",  # written once a daily is finished
            "x['next_tick'] <= time_since_epoch",             # what is due
            "key=lambda x: x['priority']",                    # the order dailies run in
            "'func_name'", "'event_name'", "'enabled'",
        ],
    },
    {
        "repo": "OneDragon-Anything/ZenlessZoneZero-OneDragon",
        "game": "Zenless Zone Zero",
        "used_in": "gachashift/games/zzz.py",
        "paths": ["src/one_dragon/base/operation"],
        "strings": [
            "指令[ ",
            "节点 %s 返回状态",
            "执行成功 返回状态",
            "执行失败 返回状态",
            "执行应用组",
            "应用已完成 ",
            '"一条龙"',
        ],
    },
    {
        "repo": "babalae/better-genshin-impact",
        "game": "Genshin Impact",
        "used_in": "gachashift/games/genshin.py",
        "paths": ["BetterGenshinImpact/GameTask"],
        "strings": [
            "邮件：{Text}",
            "探索派遣：{Text}",
            "未探索完成或已领取",
            "检查每日奖励结果：{Msg}",
            "今日奖励已领取",
            "一条龙和配置组任务结束",
        ],
    },
    {
        "repo": "babalae/bettergi-scripts-list",
        "game": "Genshin Impact",
        "used_in": "gachashift/games/genshin.py",
        "paths": ["repo/js/AutoCommissionNova"],
        "strings": ["当前每日委托奖励进度: ", "委托执行成功："],
    },
]

MAX_FILE = 5 * 1024 * 1024


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=600)


def download(repo, paths, dest):
    """The newest commit of the repo's default branch, with only the given folders."""
    git("clone", "--depth", "1", "--filter=blob:none", "--sparse", "--quiet",
        f"https://github.com/{repo}.git", dest)
    git("sparse-checkout", "set", *paths, cwd=dest)


def missing_in(folder, strings):
    """The strings that appear in no file under folder."""
    left = list(dict.fromkeys(strings))
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) > MAX_FILE:
                    continue
                with open(path, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            left = [s for s in left if s not in text]
            if not left:
                return []
    return left


def check(watch=WATCH, fetch=download):
    """[(entry, missing strings, error or None)] for every entry with a problem."""
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, entry in enumerate(watch):
            dest = os.path.join(tmp, str(i))
            try:
                fetch(entry["repo"], entry["paths"], dest)
            except (subprocess.SubprocessError, OSError) as e:
                detail = getattr(e, "stderr", "") or str(e)
                problems.append((entry, [], detail.strip().splitlines()[-1] if detail.strip() else type(e).__name__))
                continue
            missing = missing_in(dest, entry["strings"])
            if missing:
                problems.append((entry, missing, None))
            shutil.rmtree(dest, ignore_errors=True)
    return problems


def report(problems):
    lines = ["Gachashift's daily check found text that its log parsers look for, but that no "
             "longer appears in the tool's latest source. The tool's author probably reworded a "
             "log line, so the morning report may now say \"please check\" for tasks that went "
             "fine.", "",
             "每日检查发现：Gachashift 读取日志时依赖的文字，在工具最新的源码里找不到了。"
             "工具作者大概改了日志的写法，战报可能会把成功的任务写成“请检查”。", ""]
    for entry, missing, error in problems:
        lines.append(f"### {entry['game']}: [{entry['repo']}](https://github.com/{entry['repo']})")
        lines.append(f"Used in `{entry['used_in']}`. Looked in: "
                     + ", ".join(f"`{p}`" for p in entry["paths"]))
        if error:
            lines.append(f"- Could not download the source: `{error}`")
        for s in missing:
            lines.append(f"- [ ] `{s}`")
        lines.append("")
    lines += ["**To fix**: search the tool's repo for the new wording, update the parser and "
              "`tools/check_upstream.py`, then run the *Upstream watch* workflow again. "
              "It closes this issue when everything is found.", "",
              "**修复方法**：在工具的仓库里找到新的写法，同时改解析器和 `tools/check_upstream.py`，"
              "再手动运行一次 *Upstream watch*，全部找到后会自动关闭这个 issue。"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", help="write the issue text here when something is missing")
    args = parser.parse_args(argv)
    problems = check()
    if not problems:
        print("Every watched string was found.")
        return 0
    text = report(problems)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    return 1


if __name__ == "__main__":
    sys.exit(main())
