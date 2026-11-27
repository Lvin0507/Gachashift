<div align="center">

<img src="assets/gachashift.png" alt="Gachashift" width="160">

# Gachashift

**Clears your game dailies while you sleep.**

[![Release](https://img.shields.io/github/v/release/Lvin0507/Gachashift)](https://github.com/Lvin0507/Gachashift/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
![Windows](https://img.shields.io/badge/platform-Windows-0078D6)

[English](README.md) · [中文](README.zh.md) · [Download](https://github.com/Lvin0507/Gachashift/releases/latest)

</div>

## Download

Get `Gachashift-x.y.z.zip` from [Releases](../../releases), unzip it to a folder you can write to (not Program Files), and open `Gachashift.exe`. The app walks you through the setup. When a newer version is out, Home offers it; **Update** downloads it, checks it against the checksum published with the release, installs it over the old one and opens it again, keeping your settings and logs.

Windows may say it "protected your PC", because the exe isn't code-signed: choose **More info → Run anyway**.

You also need the automation tool for each game you play (MaaEnd, MAA, ok-ww, BAAS, OneDragon or BetterGI), set up and working on its own first. The app links to each one.

## What it does

| Game | Tool | What runs |
|---|---|---|
| Arknights: Endfield | [MaaEnd](https://github.com/MaaEnd/MaaEnd) | Launches the game and runs all daily tasks |
| Arknights (PC client) | [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights) | Recruitment, base shifts, credit store, rewards |
| Wuthering Waves (official or Steam) | [ok-ww](https://github.com/ok-oldking/ok-wuthering-waves) | Weekly garden task, Mondays by default |
| Blue Archive (JP PC client) | [BAAS](https://github.com/pur1fying/blue_archive_auto_script) | Cafe, lessons, arena, sweeps, crafting, rewards |
| Zenless Zone Zero (official or Steam) | [OneDragon](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon) | Redeem codes, check-in, mail, video store, coffee, rewards |
| Genshin Impact | [BetterGI](https://github.com/babalae/better-genshin-impact) | Mail, daily commissions, commission reward, expeditions, domains (resin) |

Each game can be turned on or off and given its own weekdays. When everything is done, Gachashift sends a short report to Telegram or Discord (English by default, Chinese optional). Anything you need to do by hand comes first; a game where everything worked takes one line, and only the tasks that need a look are listed:

```
🌅 Gachashift report (11-15)

📋 Needs you
• Genshin Impact: the commission reward wasn't claimed. Claim it from Katheryne with Adventurer Rank points.

『🪐 Arknights: Endfield』✅ All 16 done

『🎯 Arknights』✅ All 6 done

『📘 Blue Archive』✅ All 8 done · 13 min

『⚡ Zenless Zone Zero』✅ All 8 done · 6 min

『✨ Genshin Impact』
Daily commissions: ⚠️ Partly done (3/4)
Commission reward: ❌ Failed (未领取)
✅ The other 2 done
✅ Finished in 12 min
```

The run log under History keeps the full list of every task.

## How it works

Gachashift doesn't play the games itself. For each game it opens the right tool, waits for it to finish, closes everything it started and then reads the tool's own log. The report comes from fixed rules about each tool's start, success and failure lines, so the same log always gives the same report, and a task the rules don't know yet is shown as a new task instead of being silently ignored.

Around that, it handles the parts the tools leave to you: clicking launcher start buttons, waiting for a server's daily reset, restarting Steam with the right permissions, muting the PC (and optionally dimming the screen) while it runs, keeping Windows from sleeping or starting the screen saver in the middle of a game, and putting everything back afterwards.

If nothing in a game got done (the game didn't start, or the tool left no records), it tries that game once more after all the others. That usually happens the first morning after a client update, when the game takes too long to open. A game where some tasks worked and some failed isn't repeated, and neither is one whose first attempt ran past 40 minutes. Each game has its own switch for this; it is off for Endfield, whose tasks carry over between days. A game whose log and screen haven't changed for 15 minutes is taken as stuck and ended early, instead of holding up the morning until its timeout; a screen that can't be seen (switched off or locked) never counts as stuck.

If Gachashift itself fails, it still sends a short message with the error and where the log is, so a silent morning means the PC didn't run at all. Screenshots follow the report, so you can often see the cause (a launcher asking for an update, a game stuck on a pop-up) without going back to the PC. For MaaEnd, MAA, OneDragon and BetterGI, which write their log as they go, Gachashift reads it every few seconds and takes a picture the moment a task gets stuck or fails, before the tool moves on (at most three per game). For Genshin that is a commission that fails its last attempt, domains that end with resin left, or a commission reward left unclaimed; the picture is taken at the first sign of trouble (a fallen party, an error) and deleted if BetterGI gets past it. The screen just before Gachashift closes a game is sent only when the end itself went wrong: nothing got done, the run timed out or crashed, or the last task failed. If a run was cut off before it could send anything (a power cut, the PC switched off), the next report starts with a line saying so. When a game didn't start but its launcher was still open, the report says the client probably needs an update. While a run is going, a tray icon shows which game is running; right-click it to stop.

**Update games first** (General, off by default, experimental) handles client updates instead of only reporting them. Before the games, Gachashift checks Steam's own record of each Steam game and opens the launchers it can open by itself (Blue Archive's, and the ones Steam opens for Wuthering Waves and ZZZ) to see whether the start button has turned into an update button. A game whose launcher turns out to show an update during the run (GRYPHLINK for Endfield and Arknights too) gets its update started right there. Gachashift clicks the update button once (a second click would pause the download), answers a confirm window by clicking its main button or pressing Enter, minimizes the launcher, keeps the other games' cleanup from closing it, and runs that game after all the others, once its launcher shows the start button again. There is no fixed time limit, so a big update simply takes longer; it gives up only when nothing on the launcher has moved for 20 minutes, or after 8 hours. What the start button looks like is learned from the click that last started the game, so a launcher is checked before the run only after that has happened once. A download that stops moving (paused, or waiting for an install click) gets its button clicked again, at most three times. With the switch on, Gachashift also stops clicking a launcher button that steadily doesn't look like the start button, since clicking that spot during a download pauses it.

If you are using the PC when the scheduled time comes, it asks first and gives you 60 seconds to skip. A run can be stopped from the app at any time: the game in progress closes its tool and game, sound and brightness are restored, the PC stays on, and the report lists what was finished before the stop.

## Requirements

- Windows
- A Telegram bot or a Discord webhook, if you want the report on your phone (optional)
- The tools for your games, installed and working on their own first. Follow each tool's own documentation, then check these settings Gachashift relies on:
  - **MaaEnd**: "Launch Game (PC)" as the first task and "kill process" as the last. If it opens the Steam version, tick "MaaEnd opens the game through Steam" in Gachashift so Steam is restarted with admin rights first
  - **MAA**: connection set to PC client, "start game" path set, "run on startup" enabled
  - **ok-ww**: game path set; GardenTask configured
  - **BAAS**: "run on startup" enabled, "start emulator on startup" **disabled** (Gachashift opens the JP launcher and clicks スタート itself), "exit BAAS when done" selected
  - **OneDragon**: game path and account instance set; the apps you want enabled in the one-dragon list
  - **BetterGI**: set the game path, enable the tasks you want in a one-dragon config, and set its finishing action to close the game and BetterGI (not shut down). Each config has its own finishing action, and a new one starts empty; pick the config on Gachashift's Genshin page, which warns when its finishing action is wrong. The one-dragon's domains use up all the resin: the round count on BetterGI's own domain page doesn't apply to it
- For Steam games: Steam must sign in automatically to the account that owns the game
- The PC must stay on and signed in overnight. Turning the screen off is fine; sleep and the lock screen are not, because no tool can see or click anything on the lock screen
- Leave the PC alone during a run. BAAS and the launcher clicks use the real mouse, and moving it makes BAAS stop

## Run from source

1. Install Python 3.10 or newer (**64-bit**; the app's interface library has no 32-bit version), then the dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Double-click `Gachashift App.bat`.

The app takes it from there. Home shows a short setup checklist with a button for each step: turn on your games, tell Gachashift where each tool is, do one test run, connect Telegram or Discord (optional), and choose when to run. **Find tools** on the Games page looks for each tool and each game's exe on your PC (running ones first, then the tools' own settings, your usual folders and your Steam libraries) and fills in what it finds, without touching settings you already made. Every setting has a one-line hint under it, and each game's page links to its tool's own documentation. When all five steps are done, the checklist goes away. Home also warns about Windows settings that would stop the morning run (sleep with a password on wake, a locking screen saver, closing the lid), each with a button to the right settings page, and about tool settings that differ from the list above (it reads each tool's own config file), since a tool that never starts, never exits or puts the PC to sleep takes the next games down with it. Most of them have a **Fix it** button that changes the setting in the tool's own file (with the tool closed; the old file is kept as `.gachashift-backup`). When a game goes badly, the report adds any of these that would explain it. **Check tomorrow's run** on the Run page does every check at once without starting a game (each game's settings and paths, the schedule, Windows and tool settings) and sends a test message to Telegram / Discord. Under each game, Home shows how its last run went. Games run from top to bottom; the ▲ ▼ next to each one change the order.

Other pages:

- **Run**: run everything now, or test one game; the output appears as it happens. For a run started before bed, two switches: darken the screens, and shut the PC down when it's done (that one counts for the next run only)
- **Schedule**: the daily Task Scheduler task (highest privileges, never starts late after a missed time)
- **History**: past runs, with the report at the end. **Pack a problem report** puts the recent logs, screenshots, the end of each tool's log and your settings into one zip on the Desktop, with the Telegram token, Discord webhook, game UIDs and your Windows user name removed, ready to send to whoever helps you
- **General**: languages, mute / darken the screen / shut down while running, Telegram and Discord with a test message, the update check
- **Appearance**: a background image, panel opacity, accent colour, and an image for each game. Images are files on your PC; they stay there and are never uploaded or bundled

While a run is going on, a **Stop** button appears on every page.

### Command line

The app runs the same commands, so they also work on their own:

```
python -m gachashift                   # the scheduled run (asks first if someone is at the PC)
python -m gachashift --no-shutdown     # run everything now and keep the PC on
python -m gachashift --shutdown-after  # run everything now, then shut down
python -m gachashift --only zzz        # one game: endfield, arknights, wuthering, bluearchive, zzz or genshin
python -m gachashift --dry-run-endfield logs\go-service_<date>.log
```

Add `--lang zh` for a Chinese report.

## Logs

- `logs/gachashift_<date>.log`: everything Gachashift printed during a run, kept for 14 days. Scheduled runs have no visible console, so this is the first place to look when a report looks wrong. The app's **History** page shows the same files.
- `logs/go-service_<date>.log`: archived MaaEnd logs, kept for 14 days (MaaEnd overwrites its own log on every launch).
- `logs/screens/`: screenshots of games that didn't go well, kept for 14 days. Turn them off under General.

## Known limitations

- **Blue Archive's results come from BAAS's schedule, not a log.** BAAS doesn't write its task log to a file. It does keep `config/<name>/event.json`, where each daily's next due time moves past the next reset once the daily is finished, so Gachashift compares that file before and after the run. That shows which dailies got done and where BAAS stopped. It reflects BAAS's own idea of done: a daily BAAS thinks it finished but didn't fully do still shows ✅. If the file can't be found, the result falls back to how long BAAS ran.
- **When BAAS gets stuck, Gachashift does what you would.** If the screen stays still for 5 minutes, it taps once where BAAS itself taps to close a reward pop-up, then waits 3 more minutes. If the screen still doesn't move, or no daily gets finished for 20 minutes while BAAS keeps going round in circles, it closes BAAS and starts it again (the game stays open, and BAAS skips the dailies it already did). If BAAS gets stuck at the same daily twice, it gives up and the report names that daily: usually its settings in BAAS don't match what the game shows. The tap uses the real mouse, like the launcher clicks.
- **OneDragon updates itself on every start**, and an update that needs a driver installed waits for a click. Open OneDragon by hand once after each game update, so the morning run doesn't stop at that window.
- **Wuthering Waves only runs the weekly garden task** for now.
- **Genshin's commissions depend on BetterGI's community scripts.** Some commissions have no route yet, and a misread name or a lost fight can leave one undone; the commission reward can still be claimed with Adventurer Rank points (the 使用历练点完成每日委托 script). Turn off BetterGI's automatic script updates, so an update can't replace a script while it runs.
- **Windows only**, because every tool is Windows-only.

## Project layout

```
gachashift/           The program
  __main__.py         Command line (python -m gachashift)
  ui/                 The desktop app (PySide6; python -m gachashift.ui)
  winutil.py          Elevated runs, the Task Scheduler task, calibration, per-game settings
  runner.py           Picks today's games, waits for resets, stop requests, report, shutdown
  prompt.py           The "about to start" window for scheduled runs
  config.py           config.json, defaults, and migration from the old .env
  system.py           Processes, logs, launcher clicks, Steam, lock screen, mute and brightness
  report.py           Structured results, the Telegram and Discord messages
  updates.py          Asks GitHub whether a newer release is out
  updater.py          "Update games first": Steam and launcher updates, before and during a run
  finder.py           Finds each game's tool on the PC
  selfupdate.py       One-click update of the packaged exe
  health.py           Windows settings that would stop the morning run
  toolcheck.py        the tools' own settings Gachashift relies on, read from their config files
  preflight.py        "Check tomorrow's run": every check plus a test message
  tray.py             the tray icon while a run is going
  toolfix.py          "Fix it": changes a tool's setting to what Gachashift relies on
  buttonfind.py       finds a launcher's start button in a picture of its window
  bugreport.py        The problem report zip, with private details removed
  i18n.py             All English and Chinese text
  games/              One module per game
tests/                Log-parser tests, run on every push
tools/check_upstream.py  The log text Gachashift reads, checked against each tool's latest source
  logs/               Real log excerpts the tests read
Gachashift.py         Entry point of Gachashift.exe (opens the app, or "run" does a run)
Gachashift App.bat    Opens the app from source
build.py              Builds dist/Gachashift and its zip with PyInstaller
assets/               The app icon
.github/workflows/    Tests, the Release build, and the daily upstream watch
config.example.json   Template for config.json
logs/                 Run logs and archived MaaEnd logs (git-ignored)
```

## Lessons learned

Problems I hit while building this, and what fixed them:

- **The report said "timed out" when the real error was 503.** A bare `except:` labelled every failure as a timeout. Logging the actual HTTP status showed Gemini was overloaded at peak hours, so I added increasing backoff and a fallback model.
- **The API key could leak through error messages.** The key was in the URL query string, which `requests` includes in exception text that was then sent to Telegram. Moved it to the `x-goog-api-key` header.
- **One noisy log line made the prompt 300k characters.** A delivery task dumped ~2KB of JSON per scan; filtering those lines (and capping line length) cut it to ~13k.
- **A real failure was reported as success.** Some failures are only logged at `debug` level, and my own filter was dropping all debug lines. The fix exposed a bigger issue: asking an LLM to judge success from logs is fragile.
- **So the parsing became deterministic.** Each task has a clear start line and a clear failure line. Gachashift checks those directly, and flags any task it hasn't seen before instead of silently ignoring it. The first version used Gemini to read the logs; the current one needs no API key at all.
- **Keyword checks lie, too.** The first Wuthering Waves check looked for a few words like "completed" and reported success on a run that had failed. It now only trusts ok-ww's exact completion and failure lines.
- **Test runs read the wrong data.** MaaEnd overwrites its log on every launch, so opening it again wiped the morning's log. Each run's log is now archived.
- **MAA never exits on its own.** In PC-client mode there is no "exit when done" option, so Gachashift watches MAA's log for its completion message and closes it, reading only the part of the log written during this run.
- **Secrets started out hard-coded.** Everything sensitive now lives in a git-ignored `config.json`, and GitHub push protection blocks accidental key commits.
- **Not every game can be automated safely.** NIKKE's PC client ignores all synthetic input, and running it on a real phone through ADB earned the account a one-hour ban. I dropped it instead of trying to evade the anti-cheat.
- **The script needs a 1280x720 window, but I play full screen.** Blue Archive (Unity) keeps its window size in the registry, so Gachashift writes a 1280x720 window before launching. Restoring full screen afterwards turned out not to be possible from the registry: the game's full-screen toggle isn't stored in Unity's standard settings, and an earlier save-and-restore approach also broke once an interrupted run left the window values behind. So Gachashift only sets the window it needs, and I press Alt+Enter when I play.
- **"Wait for the process to exit" waited for the wrong process.** BAAS's `.exe` is only a launcher that starts the real script and quits. Gachashift tracks the processes running from inside each tool's folder, matching on the path so it never touches its own `python.exe`. Later BAAS started leaving `adb.exe` running after it quit, so for BAAS the run now ends when its main `pythonw.exe` exits, and the leftovers are closed.
- **Redirecting a tool's output crashed it.** BAAS's launcher prints a banner with block characters. Sent to a file, Python fell back to the system's Japanese code page (cp932), which can't encode them, and the launcher died before starting BAAS. Giving it its own console window fixed it.
- **A tool with no log can still say what it did.** BAAS logs only to its window, so for a while Blue Archive was judged by how long BAAS ran, and a run that got stuck partway was reported as "nothing got done". BAAS's scheduler file, which it rewrites after every finished daily, turned out to be a better record than any log line.
- **The JP client can't be started directly.** Running `BlueArchive.exe` by itself crashes at login, and the official launcher has no auto-start option. Gachashift opens the launcher, finds its window by process, and clicks スタート (as a fraction of the window size, so it survives DPI scaling) until the game process appears. The position is calibrated once per launcher, or found for you: launchers keep a big, evenly coloured, wide button in their lower right while the rest is game art, so Gachashift looks for the largest flat, button-shaped patch of colour there. If clicks at the saved position do nothing three times (a new monitor, a redesigned launcher), it looks for the button the same way.
- **A real-mouse click can land on the wrong window.** Windows sometimes refuses to bring a window to the front, and one morning a click meant for Blue Archive's launcher opened Endfield's instead. Gachashift now checks that the launcher really is the foreground window before clicking, and skips the click if it isn't.
- **The Steam build of ZZZ can't be launched directly.** Starting the game exe makes it quit and ask for Steam, and Steam then opens the HoYoverse launcher, which needs a click on its start button. Gachashift starts the game through `steam://rungameid/`, clicks the launcher's button the same way it does for Blue Archive, and only then hands the running game to OneDragon. A Wuthering Waves update later brought the same launcher step to its Steam build, and it is handled the same way.
- **A UAC prompt nobody can click.** ZZZ needs admin rights. Child processes inherit their parent's privileges, so when the elevated script started Steam, the game launched silently; but if Steam was already running as a normal user (it starts at login), launching the game raised a UAC prompt. UAC prompts run on a separate secure desktop that scripts deliberately can't interact with, so the run just stalled. Gachashift now closes an already-running Steam with `steam://exit` and starts it again itself, so the whole chain inherits admin rights. Wuthering Waves on Steam needed the same treatment: without Steam ready, the game closed itself a minute after ok-ww started it.
- **A tool that only exits on success.** ok-ww's `-e` flag exits after a successful run but leaves the app open after a task exception, still moving the mouse in the background, which then interfered with the next game. Gachashift now watches the tool's log for its own completion and failure lines and always closes the tool afterwards, whatever the outcome.
- **A scheduled run leaves no trace.** Task Scheduler runs have no visible console, so the first time ZZZ silently did nothing there was no way to tell why. Everything Gachashift prints now also goes to a dated log file.
- **The lock screen blinds every tool.** Testing wake-from-sleep, Windows woke up on the lock screen, where screen capture fails, so MaaEnd sat there unable to start the game. Waking without a password would have fixed it at the cost of security, so the PC stays on with the screen off instead, and Gachashift checks for the lock screen first: if it is up, the report says so rather than hanging for hours.
- **A run that starts while you're at the PC.** The first time the schedule fired while I was using the computer, games and tools kept opening and had to be closed one by one. Scheduled runs now ask first if the mouse or keyboard was used in the last two minutes, and every wait in a run checks for a stop request, so a stop takes effect within a second and still cleans up after itself.
- **A tool renamed a task, and the report said it hadn't run.** MaaEnd's stash task started logging as `StashBackpackEntry` instead of `StashBackpackMain`, so the report showed it as not run next to a "new task" that was the same thing. Endfield's task list now comes from MaaEnd itself: its `interface.json` (which task logs under which name) and the config it runs on launch. Renames line up by themselves, and a task you turned off in MaaEnd isn't shown as not run. Only when those files can't be read does Gachashift fall back to its own list.
- **Waiting for a wrong report to notice a reworded log line is too late.** Gachashift reads each tool's log, so every line it looks for is a promise the tool's author never made. `tools/check_upstream.py` lists each of those lines and the repo it comes from, and the *Upstream watch* workflow looks for them in every tool's latest source each day. When one is gone, it opens an issue the same day, usually before the change reaches a release. The same research found that MAA and ok-ww write their logs in the language their window is set to, which the parsers now read in all of them.

## Releasing

Run the tests first:

```
python -m unittest discover -s tests
```

When the *Upstream watch* workflow opens an issue, a tool changed a line Gachashift reads: find the new wording in that tool's repo, update the parser and `tools/check_upstream.py`, then run the workflow again from the Actions tab; it closes the issue once everything is found. GitHub pauses scheduled workflows in a repo with no activity for 60 days, so re-enable it there after a quiet spell.

When a report looked wrong, add that day's log to `tests/logs` with a test for what the report should have said, and fix the parser until it passes.

Set the version in `gachashift/__init__.py`, commit and push, then push a matching tag such as `v1.0.1`. GitHub Actions builds `Gachashift.exe` on Windows and publishes the Release with the zip attached; it stops if the tag and the version don't match, or if a test fails. A `.sha256` checksum of the zip is published next to it for the app's one-click update.

## Built on

Gachashift only orchestrates these tools and reads their logs — all the actual game automation is their work:

- [MaaEnd](https://github.com/MaaEnd/MaaEnd) — Arknights: Endfield
- [MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights) — Arknights
- [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) — Wuthering Waves
- [BAAS](https://github.com/pur1fying/blue_archive_auto_script) — Blue Archive
- [ZenlessZoneZero-OneDragon](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon) — Zenless Zone Zero
- [BetterGI](https://github.com/babalae/better-genshin-impact) — Genshin Impact

This repo doesn't include or redistribute any of their code. Each project has its own license; please check them before use.

## Disclaimer

For learning purposes only. Game automation may violate the games' terms of service and can get accounts banned — use at your own risk.

## License

[MIT](LICENSE)