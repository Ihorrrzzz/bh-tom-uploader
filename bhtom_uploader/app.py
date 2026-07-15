"""Application bootstrap: theme, credential migration, login -> main window."""
from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog

from . import __app_name__
from .core import credentials
from .core.bhtom import BHTOMClient
from .core.settings import Settings
from .resources import resource_path
from .ui.login_window import LoginDialog
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def run() -> int:
    QCoreApplication.setOrganizationName("BHTOM")
    QCoreApplication.setApplicationName(__app_name__)

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(resource_path("logo.png"))))
    # the app lives in the tray while the window is hidden mid-run - do not quit
    # when the last window closes; MainWindow.closeEvent decides when to exit
    app.setQuitOnLastWindowClosed(False)

    settings = Settings()
    apply_theme(app, settings.theme)
    # follow live OS light/dark switches while in "system" mode
    app.styleHints().colorSchemeChanged.connect(
        lambda *_: settings.theme == "system" and apply_theme(app, "system")
    )

    # one-time import of the legacy plaintext credentials.json into the OS keyring
    migrated = credentials.migrate_legacy_file()
    if migrated:
        settings.username = migrated

    client = BHTOMClient()
    login = LoginDialog(client, settings)
    if login.exec() != QDialog.DialogCode.Accepted:
        return 0

    window = MainWindow(client=client, settings=settings, user=login.user or {})
    window.show()
    return app.exec()
