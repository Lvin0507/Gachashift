"""Games: one page per game with its switch, weekdays and settings, each with a plain hint."""

import os
import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QVBoxLayout, QWidget

from .. import buttonfind
from ..config import app_dir
from ..games import ordered
from ..system import bring_to_front, main_window_of, move_mouse_to
from ..toolcheck import bgi_flow_names
from ..winutil import (DAY_KEYS_EN, DAY_KEYS_ZH, FIELDS, PATH_KINDS, SHORT_NAMES, STEAM_ONLY, TOOLS,
                       launcher_of, parse_point, plain_name, window_under_cursor)
from .widgets import (Choice, DayChips, Field, ImageBox, Toggle, button, label, panel, pick_file,
                      shadowed)


def build(app):
    gid = app.current_game
    game_cfg = app.cfg["games"][gid]
    page = QWidget()
    box = QVBoxLayout(page)
    box.setContentsMargins(0, 0, 8, 8)
    box.setSpacing(12)

    short = SHORT_NAMES.get(app.lang, SHORT_NAMES["en"])
    picker = Choice([(g.id, short[g.id]) for g in ordered(app.cfg)], gid)
    picker.changed.connect(app.open_game)
    top = QHBoxLayout()
    top.addWidget(picker)
    top.addStretch()
    find = button(app.tr("finder.button"), None, app.find_tools)
    find.setToolTip(app.tr("finder.tooltip"))
    top.addWidget(find)
    box.addLayout(top)

    banner = ImageBox(app.cfg["appearance"].get("game_images", {}).get(gid, ""), height=150, radius=14,
                      fixed=False)
    if banner.has_image():
        box.addWidget(banner)
    else:
        banner.deleteLater()

    box.addWidget(shadowed(label(plain_name(gid, app.lang), "h1")))
    tool, url = TOOLS[gid]
    box.addWidget(shadowed(button(app.tr("games.tool_page", tool=tool), "link", lambda: webbrowser.open(url))),
                  0, Qt.AlignLeft)

    card, inner = panel(spacing=12)
    row = QHBoxLayout()
    row.addWidget(label(app.tr("games.enabled"), "h2"))
    row.addStretch()
    toggle = Toggle(bool(game_cfg.get("enabled")))
    toggle.toggled.connect(lambda on: app.set_game_value(gid, "enabled", on))
    row.addWidget(toggle)
    inner.addLayout(row)
    days = DayChips(DAY_KEYS_ZH if app.lang == "zh" else DAY_KEYS_EN, game_cfg.get("days", []))
    days.changed.connect(lambda value: app.set_game_value(gid, "days", value))
    inner.addWidget(days)
    box.addWidget(card)

    card, inner = panel(spacing=18)
    for key, kind, extra in FIELDS[gid]:
        steam = game_cfg.get("client") == "steam" if gid == "zzz" else game_cfg.get("steam_client")
        if gid in ("zzz", "wuthering") and not steam and key in STEAM_ONLY:
            continue
        inner.addWidget(make_field(app, gid, key, kind, extra))
    box.addWidget(card)
    box.addStretch()
    return page


def make_field(app, gid, key, kind, extra):
    game_cfg = app.cfg["games"][gid]
    title, hint = app.tr(f"f.{key}"), app.tr(f"h.{key}")

    if kind == "bool":
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        check = QCheckBox(title)
        check.setChecked(bool(game_cfg.get(key)))
        def toggled(on):
            app.set_game_value(gid, key, on)
            if key == "steam_client":
                app.show_page("games")  # Steam-only settings appear or disappear

        check.toggled.connect(toggled)
        col.addWidget(check)
        col.addWidget(label(hint, "hint", wrap=True))
        return holder

    if kind == "choice":
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addWidget(label(title, "h2"))
        col.addWidget(label(hint, "hint", wrap=True))
        choice = Choice([(v, app.tr(f"choice.{v}")) for v in extra], game_cfg.get(key, extra[0]))

        def picked(value):
            app.set_game_value(gid, key, value)
            if key == "client":
                app.show_page("games")  # Steam-only settings appear or disappear

        choice.changed.connect(picked)
        col.addWidget(choice)
        return holder

    if kind == "bgi_config":
        return bgi_config_field(app, gid, key, title, hint)

    value = game_cfg.get(key, "")
    if kind == "point":
        value = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
    side_text = on_side = None
    field = None
    if kind in PATH_KINDS:
        side_text = app.tr("browse")
        on_side = lambda: (lambda p: p and field.edit.setText(p))(pick_file(app, kind, field.edit.text()))
    elif kind == "point":
        side_text = app.tr("calib.button")
        on_side = lambda: calibrate(app, gid, field.edit)
    field = Field(title, hint, value or "", side_text, on_side)

    def check(text):
        text = text.strip()
        message = ""
        if kind == "point":
            point = parse_point(text)
            if point:
                game_cfg[key] = point
            else:
                message = app.tr("button.invalid")
        else:
            game_cfg[key] = text
            if kind in PATH_KINDS and text and not os.path.exists(text):
                message = app.tr("path.missing")
        field.set_error(message)
        app.changed()

    field.edit.textChanged.connect(check)
    if value:
        check(field.edit.text())  # show problems with the saved value straight away
    return field


class FlowPicker(QComboBox):
    """BetterGI's one-dragon configs, read again each time the list opens (the BetterGI path
    may have just been filled in, or a config added in BetterGI). A name can still be typed."""

    def __init__(self, names_now, value):
        super().__init__()
        self.names_now = names_now
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.refill(value)

    def refill(self, value):
        self.blockSignals(True)
        self.clear()
        self.addItems(self.names_now())
        self.setEditText(value)
        self.blockSignals(False)

    def showPopup(self):
        self.refill(self.currentText())
        super().showPopup()


def bgi_config_field(app, gid, key, title, hint):
    game_cfg = app.cfg["games"][gid]
    holder = QWidget()
    col = QVBoxLayout(holder)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(4)
    col.addWidget(label(title, "h2"))
    col.addWidget(label(hint, "hint", wrap=True))
    names = lambda: bgi_flow_names(game_cfg.get("bgi_path", ""))
    picker = FlowPicker(names, game_cfg.get(key, ""))
    picker.lineEdit().setPlaceholderText("默认配置")   # what runs when it's left empty
    col.addWidget(picker)
    error = label("", "error")
    error.hide()
    col.addWidget(error)

    def check(text):
        text = text.strip()
        if game_cfg.get(key, "") != text:
            game_cfg[key] = text
            app.changed()
        found = names()
        # only when BetterGI's configs can be read: otherwise there's nothing to compare with
        message = app.tr("bgi.config_missing") if found and (text or "默认配置") not in found else ""
        error.setText(message)
        error.setVisible(bool(message))

    picker.currentTextChanged.connect(check)
    check(picker.currentText())
    return holder


def calibrate(app, gid, edit):
    """Read the launcher's start button position from where the mouse rests after a countdown,
    and check that the window under the mouse really is that launcher."""
    expected = launcher_of(gid, app.cfg["games"][gid])
    dialog = QDialog(app)
    dialog.setWindowTitle(app.tr("calib.title"))
    dialog.setWindowFlag(Qt.WindowStaysOnTopHint)
    dialog.setStyleSheet(f"QDialog {{ background: #141B2D; }}")
    col = QVBoxLayout(dialog)
    col.setContentsMargins(22, 18, 22, 18)
    col.setSpacing(12)
    col.addWidget(label(app.tr("calib.explain", launcher=expected), None, wrap=True))
    message = label("", "h2", wrap=True)
    col.addWidget(message)
    row = QHBoxLayout()
    start = button(app.tr("calib.start"))
    auto = button(app.tr("calib.auto"))
    use = button(app.tr("calib.use"), "primary")
    use.hide()
    row.addWidget(start)
    row.addWidget(auto)
    row.addStretch()
    row.addWidget(use)
    col.addLayout(row)
    found = {}
    timer = QTimer(dialog)
    count = {"n": 0}

    def tick():
        count["n"] -= 1
        if count["n"] > 0:
            message.setText(app.tr("calib.countdown", n=count["n"]))
            return
        timer.stop()
        exe, x, y = window_under_cursor()
        if x is None or exe.lower() != expected.lower():
            message.setText(app.tr("calib.wrong", exe=exe, expected=expected))
        else:
            found.update(x=x, y=y)
            message.setText(app.tr("calib.found", exe=exe, x=x, y=y))
            use.show()
        start.setText(app.tr("calib.again"))
        start.setEnabled(True)

    def begin():
        use.hide()
        start.setEnabled(False)
        count["n"] = 6
        tick()
        timer.start(1000)

    def look():
        """Find the button in the launcher's window, and put the mouse on it to show where."""
        use.hide()
        hwnd = main_window_of(expected)
        if not hwnd:
            message.setText(app.tr("calib.no_window", launcher=expected))
            return
        picture = buttonfind.grab_client(hwnd) if bring_to_front(hwnd) else None
        point = buttonfind.find_button(*picture) if picture else None
        dialog.raise_()
        if not point:
            # keep what was looked at, so a launcher it can't read can be worked out later
            path = app_dir() / "logs" / f"buttonfind_{os.path.splitext(expected)[0]}.png"
            try:
                path.parent.mkdir(exist_ok=True)
                saved = picture and buttonfind.save_picture(picture, path)
            except Exception:
                saved = False
            message.setText(app.tr("calib.auto_none") + ("\n" + app.tr("calib.auto_saved", path=path) if saved else ""))
            return
        found.update(x=point[0], y=point[1])
        move_mouse_to(hwnd, *point)
        message.setText(app.tr("calib.auto_found", x=point[0], y=point[1]))
        use.show()

    timer.timeout.connect(tick)
    start.clicked.connect(begin)
    auto.clicked.connect(look)
    use.clicked.connect(lambda: (edit.setText(f"{found['x']}, {found['y']}"), dialog.accept()))
    dialog.move(40, 40)
    dialog.resize(420, 180)
    dialog.show()
