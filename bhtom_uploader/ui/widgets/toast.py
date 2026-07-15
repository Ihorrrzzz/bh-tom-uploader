"""Bottom-right completion toast with a light-curve thumbnail.

Frameless, always-on-top, never steals focus; auto-dismisses after ~60 s with
a fade. Clicking the thumbnail (or "Full light curve") opens the interactive
plot; "BHTOM page" opens the target on the website.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

DEFAULT_TIMEOUT_MS = 60_000


class Toast(QWidget):
    _instance: Optional["Toast"] = None

    def __init__(
        self,
        title: str,
        pixmap: Optional[QPixmap] = None,
        on_open_plot: Optional[Callable[[], None]] = None,
        on_open_page: Optional[Callable[[], None]] = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._on_open_plot = on_open_plot
        self._fade: Optional[QPropertyAnimation] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("toastFrame")
        outer.addWidget(frame)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("toastTitle")
        title_label.setWordWrap(True)
        close_button = QToolButton(text="✕")
        close_button.setObjectName("toastClose")
        close_button.clicked.connect(self.close)
        header.addWidget(title_label, 1)
        header.addWidget(close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        if pixmap is not None and not pixmap.isNull():
            thumb = QLabel()
            thumb.setPixmap(pixmap.scaledToWidth(352, Qt.TransformationMode.SmoothTransformation))
            thumb.setCursor(Qt.CursorShape.PointingHandCursor)
            thumb.setToolTip("Open the full interactive light curve")
            thumb.mousePressEvent = lambda _e: self._open_plot()  # simple click hook
            layout.addWidget(thumb)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if on_open_plot is not None:
            plot_button = QPushButton("Full light curve")
            plot_button.setObjectName("toastAction")
            plot_button.clicked.connect(self._open_plot)
            buttons.addWidget(plot_button)
        if on_open_page is not None:
            page_button = QPushButton("BHTOM page")
            page_button.setObjectName("toastAction")
            page_button.clicked.connect(lambda: (on_open_page(), None)[1])
            buttons.addWidget(page_button)
        layout.addLayout(buttons)

        self.setFixedWidth(380)
        QTimer.singleShot(timeout_ms, self._fade_out)

    # ------------------------------------------------------------------
    def _open_plot(self) -> None:
        if self._on_open_plot is not None:
            self._on_open_plot()

    def _fade_out(self) -> None:
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(600)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.close)
        self._fade.start()

    def show_at_corner(self) -> None:
        self.adjustSize()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(
            screen.right() - self.width() - 16,
            screen.bottom() - self.sizeHint().height() - 16,
        )
        self.show()
        self.raise_()

    # ------------------------------------------------------------------
    @classmethod
    def show_toast(cls, *args, **kwargs) -> "Toast":
        if cls._instance is not None:
            try:
                cls._instance.close()
            except RuntimeError:
                pass  # already deleted
        toast = cls(*args, **kwargs)
        cls._instance = toast
        toast.destroyed.connect(lambda: setattr(cls, "_instance", None))
        toast.show_at_corner()
        return toast
