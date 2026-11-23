"""History: read past runs, newest first. The report is at the end of each run."""

import os
import subprocess

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from .. import bugreport
from ..config import app_dir
from ..system import read_since
from .widgets import button, label, panel, shadowed


def open_folder(folder):
    folder.mkdir(exist_ok=True)
    os.startfile(str(folder))


def pack_report(app):
    """Make the problem report zip and show it in Explorer."""
    try:
        path = bugreport.build(app.cfg)
    except OSError as e:
        app.set_status(app.tr("history.report_failed", error=e), "fail")
        return
    app.set_status(app.tr("history.report_done", name=path.name), "ok")
    subprocess.Popen(["explorer", "/select,", str(path)])


def report_button(app):
    widget = button(app.tr("history.report"), None, lambda: pack_report(app))
    widget.setToolTip(app.tr("history.report_hint"))
    return widget


def build(app):
    page = QWidget()
    box = QVBoxLayout(page)
    box.setContentsMargins(0, 0, 8, 8)
    box.setSpacing(12)
    box.addWidget(shadowed(label(app.tr("nav.history"), "h1")))

    folder = app_dir() / "logs"
    runs = sorted(folder.glob("gachashift_*.log"), reverse=True) if folder.exists() else []
    if not runs:
        card, inner = panel()
        inner.addWidget(label(app.tr("history.empty"), "muted", wrap=True))
        inner.addWidget(button(app.tr("history.open_folder"), None, lambda: open_folder(folder)))
        inner.addWidget(report_button(app))
        box.addWidget(card)
        box.addStretch()
        return page

    dates = {path.stem.replace("gachashift_", ""): path for path in runs}
    row = QHBoxLayout()
    row.addWidget(shadowed(label(app.tr("history.pick"), "muted")))
    picker = QComboBox()
    picker.addItems(list(dates))
    row.addWidget(picker)
    row.addStretch()
    # when something goes wrong, "send me today's file" is easier than explaining the path
    row.addWidget(button(app.tr("history.open_folder"), None, lambda: open_folder(folder)))
    row.addWidget(report_button(app))
    box.addLayout(row)

    output = QPlainTextEdit()
    output.setReadOnly(True)
    output.setMinimumHeight(420)

    def show(date):
        output.setPlainText(read_since(str(dates[date]), 0))
        output.verticalScrollBar().setValue(output.verticalScrollBar().maximum())

    picker.currentTextChanged.connect(show)
    show(picker.currentText())
    box.addWidget(output, 1)
    return page
