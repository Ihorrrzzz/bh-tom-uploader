"""System tray: keep working after the window is closed; control the run."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..resources import resource_path


class TrayManager(QObject):
    open_requested = Signal()
    pause_toggled = Signal(bool)
    stop_requested = Signal()
    stop_watch_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.icon = QSystemTrayIcon(QIcon(str(resource_path("logo.png"))), parent)

        menu = QMenu()
        self._act_open = QAction("Open BHTOM Uploader", menu)
        font = self._act_open.font()
        font.setBold(True)
        self._act_open.setFont(font)
        self._act_open.triggered.connect(self.open_requested)
        menu.addAction(self._act_open)
        menu.addSeparator()

        self._act_pause = QAction("Pause uploads", menu, checkable=True, enabled=False)
        self._act_pause.toggled.connect(self.pause_toggled)
        menu.addAction(self._act_pause)

        self._act_stop = QAction("Stop current run", menu, enabled=False)
        self._act_stop.triggered.connect(self.stop_requested)
        menu.addAction(self._act_stop)

        self._act_stop_watch = QAction("Stop watching folder", menu, visible=False)
        self._act_stop_watch.triggered.connect(self.stop_watch_requested)
        menu.addAction(self._act_stop_watch)

        menu.addSeparator()
        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(self.quit_requested)
        menu.addAction(act_quit)

        self._menu = menu  # keep alive
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)
        self.set_state()
        self.icon.show()

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()

    # ------------------------------------------------------------------
    def set_state(self, running: bool = False, watching: bool = False, paused: bool = False) -> None:
        self._act_pause.setEnabled(running)
        if self._act_pause.isChecked() != paused:
            self._act_pause.blockSignals(True)
            self._act_pause.setChecked(paused)
            self._act_pause.blockSignals(False)
        self._act_stop.setEnabled(running)
        self._act_stop_watch.setVisible(watching)
        if running:
            state = "uploading (paused)" if paused else "uploading…"
        elif watching:
            state = "watching folder for new files"
        else:
            state = "idle"
        self.icon.setToolTip(f"BHTOM Uploader - {state}")

    def notify(self, title: str, message: str) -> None:
        self.icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 5000)

    def hide(self) -> None:
        self.icon.hide()
