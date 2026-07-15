"""Login dialog: card layout, keyring-backed remember-me, live token validation."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..core import credentials
from ..core.bhtom import BHTOMClient
from ..core.settings import Settings, get_bhtom_url
from .theme import tinted_icon
from ..resources import resource_path
from .worker import start_worker


class LoginDialog(QDialog):
    """Sign in to BHTOM; exposes ``.user`` (users/me record) after accept()."""

    def __init__(self, client: BHTOMClient, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.settings = settings
        self.user: Optional[dict] = None

        self.setWindowTitle("BHTOM Uploader - Sign in")
        self.setModal(True)
        self.setFixedWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(10)

        logo = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(resource_path("logo.png")))
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaledToHeight(64, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(logo)

        title = QLabel("Welcome back", alignment=Qt.AlignmentFlag.AlignCenter)
        font = title.font()
        font.setPointSize(16)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        subtitle = QLabel("Sign in to your BHTOM account", alignment=Qt.AlignmentFlag.AlignCenter)
        subtitle.setObjectName("subtle")
        layout.addWidget(subtitle)
        layout.addSpacing(8)

        form = QFormLayout()
        form.setSpacing(8)
        self.username_edit = QLineEdit(placeholderText="username")
        self.password_edit = QLineEdit(placeholderText="password")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        # eye toggle inside the field (the original app's icons, web-style),
        # tinted to the active theme so it stays visible on any input background
        eye_color = self.palette().color(QPalette.ColorRole.Text)
        eye_color.setAlphaF(0.72)
        self._icon_hidden = tinted_icon(resource_path("hidden.png"), eye_color)
        self._icon_visible = tinted_icon(resource_path("visible.png"), eye_color)
        self._eye_action = self.password_edit.addAction(
            self._icon_hidden, QLineEdit.ActionPosition.TrailingPosition
        )
        self._eye_action.setToolTip("Show password")
        self._eye_action.triggered.connect(self._toggle_password)
        form.addRow("Username", self.username_edit)
        form.addRow("Password", self.password_edit)
        layout.addLayout(form)

        self.remember = QCheckBox("Remember me")
        layout.addWidget(self.remember)

        self.error_label = QLabel()
        self.error_label.setObjectName("errorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.sign_in = QPushButton("Sign in")
        self.sign_in.setObjectName("primary")
        self.sign_in.setDefault(True)
        self.sign_in.clicked.connect(self._on_submit)
        layout.addWidget(self.sign_in)

        site = QLabel(
            f'<a href="{get_bhtom_url()}">Forgot password? Open BHTOM website</a>',
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        site.setOpenExternalLinks(True)
        site.setObjectName("subtle")
        layout.addWidget(site)

        self._prefill()

    # ------------------------------------------------------------------
    def _prefill(self) -> None:
        username = self.settings.username
        if not username:
            return
        self.username_edit.setText(username)
        password = credentials.load_password(username)
        if password:
            self.password_edit.setText(password)
            self.remember.setChecked(True)
            self.sign_in.setFocus()
        else:
            self.password_edit.setFocus()

    def _toggle_password(self) -> None:
        hidden = self.password_edit.echoMode() == QLineEdit.EchoMode.Password
        self.password_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password
        )
        self._eye_action.setIcon(self._icon_visible if hidden else self._icon_hidden)
        self._eye_action.setToolTip("Hide password" if hidden else "Show password")

    def _set_busy(self, busy: bool) -> None:
        for widget in (self.username_edit, self.password_edit, self.remember, self.sign_in):
            widget.setEnabled(not busy)
        self.sign_in.setText("Signing in…" if busy else "Sign in")

    def _on_submit(self) -> None:
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            self._show_error("Please enter both username and password.")
            return
        self.error_label.hide()
        self._set_busy(True)

        def do_login():
            self.client.login(username, password)
            return self.client.me()

        start_worker(do_login, on_result=self._on_success, on_error=self._on_error)

    def _on_success(self, me: dict) -> None:
        username = self.username_edit.text().strip()
        self.user = me or {}
        self.settings.username = username
        try:
            if self.remember.isChecked():
                credentials.save_credentials(username, self.password_edit.text())
            else:
                credentials.delete_credentials(username)
        except credentials.CredentialsError:
            pass  # keyring unavailable - never block login over it
        self.accept()

    def _on_error(self, message: str) -> None:
        self._set_busy(False)
        self._show_error(message)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()
