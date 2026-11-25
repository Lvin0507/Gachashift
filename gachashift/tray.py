"""A tray icon while a run is going: hover it to see which game is running, right-click it to
stop. The run has no window, so without it a scheduled run is invisible until the report.

Qt only handles the icon's clicks while the run waits in system.pause(), which happens at
least every few seconds in every game, so the menu can take a moment to respond."""

import sys
from pathlib import Path

from . import system
from .i18n import t


def icon_file():
    """assets/gachashift.ico from source, or the copy bundled inside the exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    path = base / "assets" / "gachashift.ico"
    return str(path) if path.exists() else None


class RunTray:
    def __init__(self, lang):
        self.lang = lang
        self.icon = self.app = self.title = None
        try:
            from PySide6.QtGui import QAction, QIcon
            from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon
            self.app = system._QT_APP = QApplication.instance() or QApplication([])
            self.app.setQuitOnLastWindowClosed(False)
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
            path = icon_file()
            image = QIcon(path) if path else self.app.style().standardIcon(QStyle.SP_MediaPlay)
            self.icon = QSystemTrayIcon(image)
            self.menu = QMenu()
            self.title = QAction(t(lang, "tray.starting"), self.menu)
            self.title.setEnabled(False)
            self.menu.addAction(self.title)
            self.menu.addSeparator()
            stop = QAction(t(lang, "tray.stop"), self.menu)
            stop.triggered.connect(self.stop)
            self.menu.addAction(stop)
            self.icon.setContextMenu(self.menu)
            self.icon.setToolTip("Gachashift: " + t(lang, "tray.starting"))
            self.icon.show()
            system.set_pump(self.pump)
            self.pump()
        except Exception as e:  # no icon is fine; the run itself matters
            print(f"tray icon unavailable: {type(e).__name__}: {e}")
            self.icon = None

    def stop(self):
        system.stop_file().touch()
        self.status(t(self.lang, "tray.stopping"))

    def status(self, text):
        if self.icon is None:
            return
        self.title.setText(text)
        self.icon.setToolTip(("Gachashift: " + text)[:127])  # Windows cuts tooltips at 127
        self.pump()

    def pump(self):
        if self.app is not None:
            self.app.processEvents()

    def close(self):
        system.set_pump(None)
        if self.icon is not None:
            self.icon.hide()
            self.icon = None
            self.pump()
