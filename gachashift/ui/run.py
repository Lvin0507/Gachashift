"""Run: run everything now, or test one game, and watch the output as it happens.
The run itself lives in the window (it keeps going when you switch pages)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from ..games import ordered
from ..system import read_since
from ..toolfix import can_fix
from ..winutil import SHORT_NAMES, plain_name
from .widgets import Choice, button, label, panel, shadowed


def build(app):
    page = QWidget()
    box = QVBoxLayout(page)
    box.setContentsMargins(0, 0, 8, 8)
    box.setSpacing(12)
    box.addWidget(shadowed(label(app.tr("test.heading"), "h1")))
    box.addWidget(shadowed(label(app.tr("test.explain"), "muted", wrap=True)))
    busy = app.run_busy()

    card, inner = panel(spacing=6)
    inner.addWidget(label(app.tr("run.all"), "h2"))
    inner.addWidget(label(app.tr("run.all_explain"), "hint", wrap=True))
    run_all = button(app.tr("run.all"), "primary", lambda: app.start_run("--no-shutdown"))
    run_all.setEnabled(not busy)
    row = QHBoxLayout()
    row.addWidget(run_all)
    row.addStretch()
    inner.addSpacing(6)
    inner.addLayout(row)
    box.addWidget(card)

    card, inner = panel(spacing=6)
    inner.addWidget(label(app.tr("run.one"), "h2"))
    inner.addWidget(label(app.tr("run.one_explain"), "hint", wrap=True))
    short = SHORT_NAMES.get(app.lang, SHORT_NAMES["en"])
    picker = Choice([(g.id, short[g.id]) for g in ordered(app.cfg)], app.test_game)
    one = button(app.tr("test.run", game=short[app.test_game]), None,
                 lambda: app.start_run("--only", app.test_game))
    one.setEnabled(not busy)

    def pick(gid):
        app.test_game = gid
        one.setText(app.tr("test.run", game=short[gid]))

    picker.changed.connect(pick)
    inner.addSpacing(4)
    inner.addWidget(picker)
    row = QHBoxLayout()
    row.addWidget(one)
    row.addStretch()
    inner.addSpacing(6)
    inner.addLayout(row)
    box.addWidget(card)
    app.run_buttons = [run_all, one]
    box.addWidget(preflight_card(app))

    app.run_status = shadowed(label(app.tr("test.running") if busy else "", "muted"))
    box.addWidget(app.run_status)
    output = QPlainTextEdit()
    output.setReadOnly(True)
    output.setMinimumHeight(300)
    if app.run_log:
        output.setPlainText(read_since(app.run_log, app.run_start_offset))
        output.verticalScrollBar().setValue(output.verticalScrollBar().maximum())
    app.run_output = output
    box.addWidget(output, 1)
    return page


def preflight_card(app):
    """Will tomorrow morning's run work? Every check at once, plus a test message."""
    card, inner = panel(spacing=6)
    inner.addWidget(label(app.tr("preflight.title"), "h2"))
    inner.addWidget(label(app.tr("preflight.explain"), "hint", wrap=True))
    if app.cfg != app.saved_cfg:
        inner.addWidget(label(app.tr("preflight.unsaved"), "muted", wrap=True))
    busy = app.preflight == "busy"
    start = button(app.tr("preflight.checking") if busy else app.tr("preflight.start"), None,
                   app.start_preflight)
    start.setEnabled(not busy)
    row = QHBoxLayout()
    row.addWidget(start)
    row.addStretch()
    inner.addSpacing(6)
    inner.addLayout(row)
    if isinstance(app.preflight, tuple):
        problems, reached = app.preflight
        inner.addSpacing(6)
        if not problems:
            inner.addWidget(label(app.tr("preflight.all_good"), "ok", wrap=True))
        for problem in problems:
            line = QHBoxLayout()
            line.addWidget(label("• " + problem_text(app, problem), "hint", wrap=True), 1)
            if problem.game and can_fix(problem.game, problem.key):
                line.addWidget(button(app.tr("fix.button"), None, lambda _=False, p=problem: app.fix_tool(p)),
                               0, Qt.AlignTop)
            if problem.fix:
                line.addWidget(button(app.tr("health.open"), None,
                                      lambda _=False, fix=problem.fix: app.open_fix(fix)), 0, Qt.AlignTop)
            inner.addLayout(line)
        if reached:
            inner.addWidget(label(app.tr("preflight.sent", channels=" / ".join(reached)), "muted", wrap=True))
    return card


def problem_text(app, problem):
    params = dict(problem.params)
    if problem.key == "preflight.missing":
        sep = "、" if app.lang == "zh" else ", "
        params["items"] = sep.join(app.tr(f"f.{key}") for key in params.get("items", []))
    text = app.tr(problem.key, **params)
    if problem.game:
        text = app.tr("health.tool_prefix", game=plain_name(problem.game, app.lang)) + text
    return text
