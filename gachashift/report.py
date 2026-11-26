"""Structured results, so each game's outcome can be rendered in any language later."""

import datetime
import html
import json
import os
import re
from dataclasses import dataclass, field

import requests

from .i18n import STRINGS, game_name, t, task_label

OK, FAIL, SKIPPED, ALREADY, PARTIAL, WARN, NOTHING = (
    "ok", "fail", "skipped", "already", "partial", "warn", "nothing")
CLEAN = (OK, ALREADY, NOTHING)          # nothing to look at
SUCCESS = CLEAN + (PARTIAL,)            # at least something got done
INFO_NOTES = ("note.finished", "note.retried")  # notes that don't mean a problem


@dataclass
class TaskResult:
    key: str              # raw task name from the tool's log (or our own id)
    status: str           # one of the constants above
    detail: str = ""      # language-neutral extra info, e.g. "3/3" or "x4"
    new: bool = False     # task the label table doesn't know yet


@dataclass
class GameReport:
    game: str
    tasks: list = field(default_factory=list)
    notes: list = field(default_factory=list)   # (string key, params) pairs
    seconds: float = 0                          # how long the tool ran, not counting waits
    screenshot: str = ""                        # the screen before cleanup, kept if it went badly
    labels: dict = field(default_factory=dict)  # {task key: {lang: name}} from the tool itself

    def label(self, key, lang):
        """A task's display name: ours if we have one, else the tool's own, else its key."""
        ours = task_label(self.game, key, lang)
        if ours != key:
            return ours
        theirs = self.labels.get(key, {})
        return theirs.get(lang) or theirs.get("en") or key

    def add(self, key, status, detail="", new=False):
        self.tasks.append(TaskResult(key, status, detail, new))

    def note(self, key, **params):
        self.notes.append((key, params))


def render_game(report, lang):
    lines = [f"『{game_name(report.game, lang)}』"]
    for task in report.tasks:
        label = report.label(task.key, lang)
        if task.new:
            label += " " + t(lang, "note.new_task")
        status = t(lang, f"status.{task.status}")
        if task.detail:
            status += f" ({task.detail})"
        lines.append(f"{label}: {status}" if lang == "en" else f"{label}：{status}")
    for key, params in report.notes:
        # params that are themselves string keys (e.g. "hint.steam") get translated too
        params = {k: t(lang, v) if isinstance(v, str) and v.startswith("hint.") else v
                  for k, v in params.items()}
        lines.append(t(lang, key, **params))
    return "\n".join(lines)


def nothing_done(report):
    """True when no task in the game got done and the tool didn't say it finished."""
    if any(task.status in SUCCESS for task in report.tasks):
        return False
    return not any(key in ("note.finished", "note.quick_exit") for key, _ in report.notes)


def outcome(report):
    """"ok" (nothing to look at), "fail" (nothing got done) or "warn" (something in between)."""
    if nothing_done(report):
        return "fail"
    clean = (all(task.status in CLEAN for task in report.tasks)
             and all(key in INFO_NOTES for key, _ in report.notes))
    return "ok" if clean else "warn"


def short_name(game, lang):
    """Game name without its emoji, for sentences."""
    name = game_name(game, lang)
    return name.split(" ", 1)[1] if " " in name and not name[0].isalnum() else name


def actions(report, lang):
    """What the player has to do by hand after this game's run, one sentence each."""
    if report.game == "system":
        return []  # these notes speak for themselves at the top of the report
    game = short_name(report.game, lang)
    if outcome(report) != "ok" and any(key == "note.maybe_update" for key, _ in report.notes):
        return [t(lang, "action.update_client", game=game)]
    if outcome(report) == "fail":
        missing = any("missing settings" in str(p.get("error", "")) for _, p in report.notes)
        return [t(lang, "action.setup" if missing else "action.nothing_done", game=game)]
    found = []
    for task in report.tasks:
        if task.status != FAIL:
            continue
        # a few failures have a known fix; the rest get the general sentence
        special = f"action.{report.game}.{task.key}"
        if special in STRINGS.get(lang, {}) or special in STRINGS["en"]:
            found.append(t(lang, special, game=game))
        else:
            found.append(t(lang, "action.task_failed", game=game,
                           task=report.label(task.key, lang)))
    return found


def render_compact(report, lang):
    """A game where everything is fine takes one line; otherwise only the tasks that need a
    look are listed, with a count of the rest."""
    if report.game == "system" or outcome(report) != "ok":
        if report.game == "system":
            return render_game(report, lang)
        problems = [task for task in report.tasks if task.status not in CLEAN]
        rest = len(report.tasks) - len(problems)
        lines = render_game(GameReport(report.game, problems, report.notes), lang).split("\n")
        if rest:
            # the count goes right after the listed tasks, before the notes
            lines.insert(1 + len(problems), t(lang, "compact.rest_done", n=rest))
        return "\n".join(lines)
    notes = dict(report.notes)
    if len(report.tasks) == 1:
        # one task: show it on the same line, so details like "(max)" stay visible
        line = render_game(GameReport(report.game, report.tasks), lang).replace("\n", "")
    else:
        line = f"『{game_name(report.game, lang)}』" + (
            t(lang, "compact.all_done", n=len(report.tasks)) if report.tasks
            else t(lang, "compact.done"))
    if "note.finished" in notes:
        line += t(lang, "compact.minutes", minutes=notes["note.finished"]["minutes"])
    if "note.retried" in notes:
        line += t(lang, "compact.retried")
    return line


def render_all(reports, lang, compact=False):
    """The whole report. compact: the version sent to phones, with what needs the player
    first; the full one goes to the run log (History)."""
    if not compact:
        return "\n\n".join(render_game(r, lang) for r in reports)
    todo = [line for r in reports for line in actions(r, lang)]
    head = (t(lang, "actions.title") + "\n" + "\n".join(f"• {line}" for line in todo)
            if todo else t(lang, "actions.none"))
    return "\n\n".join([head] + [render_compact(r, lang) for r in reports])


def send_telegram(token, chat_id, reports, lang):
    """Send the report; fall back to plain text if Telegram rejects the HTML."""
    title = t(lang, "report.title", date=datetime.datetime.now().strftime("%m-%d"))
    body = render_all(reports, lang, compact=True)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    text = f"<b>{html.escape(title)}</b>\n\n{html.escape(body)}"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=15)
        if r.ok:
            return True
        plain = html.unescape(re.sub(r"</?b>", "", text))
        return requests.post(url, json={"chat_id": chat_id, "text": plain}, timeout=15).ok
    except requests.exceptions.RequestException as e:
        print(f"Telegram failed: {type(e).__name__}")
        return False


def send_text(cfg, text):
    """Send one plain message to every channel that is turned on (used when there is no
    report to send, e.g. after a crash). Never raises: it may run while handling an error."""
    tg, dc = cfg.get("telegram", {}), cfg.get("discord", {})
    try:
        if tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id"):
            requests.post(f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage",
                          json={"chat_id": tg["chat_id"], "text": text}, timeout=15)
        if dc.get("enabled") and dc.get("webhook_url"):
            requests.post(dc["webhook_url"], json={"content": text[:2000]}, timeout=15)
    except Exception as e:
        print(f"Could not send the message: {type(e).__name__}")


def send_photos(cfg, photos):
    """Send (caption, image path) pairs to every channel that is turned on, after the report.
    Never raises: a picture that can't be sent mustn't stop the run from finishing."""
    tg, dc = cfg.get("telegram", {}), cfg.get("discord", {})
    for caption, path in photos:
        try:
            if tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id"):
                with open(path, "rb") as f:
                    requests.post(f"https://api.telegram.org/bot{tg['bot_token']}/sendPhoto",
                                  data={"chat_id": tg["chat_id"], "caption": caption},
                                  files={"photo": f}, timeout=60)
            if dc.get("enabled") and dc.get("webhook_url"):
                with open(path, "rb") as f:
                    requests.post(dc["webhook_url"], data={"payload_json": json.dumps({"content": caption})},
                                  files={"file": (os.path.basename(path), f, "image/jpeg")}, timeout=60)
        except Exception as e:
            print(f"Could not send the screenshot: {type(e).__name__}")


# Discord card colours: everything fine, something to look at, something didn't get done
CARD_OK, CARD_WARN, CARD_FAIL = 0x7BD3A0, 0xE8C27C, 0xEF7D7D


def card_colour(reports):
    """The colour of the worst result: red if any game got nothing done, yellow for anything
    else worth a look (including notes such as a stop or the lock screen), green otherwise."""
    games = [r for r in reports if r.game != "system"]
    if any(outcome(r) == "fail" for r in games):
        return CARD_FAIL
    if any(outcome(r) != "ok" for r in games) or any(r.notes for r in reports if r.game == "system"):
        return CARD_WARN
    return CARD_OK


def discord_cards(reports, lang, limit=4000):
    """The report as Discord embeds (one per message), coloured by card_colour. A card holds
    up to 4096 characters, so a long report is split between lines over several cards."""
    title = t(lang, "report.title", date=datetime.datetime.now().strftime("%m-%d"))
    colour = card_colour(reports)
    chunks, current = [], ""
    for line in render_all(reports, lang, compact=True).splitlines():
        line = line[:limit]
        if current and len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current.strip():
        chunks.append(current)
    cards = [{"description": chunk, "color": colour} for chunk in chunks]
    if cards:
        cards[0]["title"] = title
    return cards


def send_discord(webhook_url, reports, lang):
    """Send the report to a Discord channel through a webhook, as coloured cards."""
    try:
        for card in discord_cards(reports, lang):
            r = requests.post(webhook_url, json={"embeds": [card]}, timeout=15)
            if not r.ok:
                print(f"Discord failed: HTTP {r.status_code}")
                return False
        return True
    except requests.exceptions.RequestException as e:
        print(f"Discord failed: {type(e).__name__}")
        return False
