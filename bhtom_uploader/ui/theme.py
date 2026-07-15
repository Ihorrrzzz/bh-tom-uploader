"""Theme: Qt Fusion style + hand-built light/dark palettes + thin QSS accent layer.

Dark-first (astronomy norm), light fully supported, follows the OS scheme via
``QStyleHints.colorScheme()`` unless the user overrides in settings.
One accent color (BHTOM red) for primary actions; semantic colors reserved for
status chips.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap

ACCENT = "#DE3B40"          # BHTOM red - primary actions/selection only
ACCENT_HOVER = "#E35257"

# semantic status colors (readable on both themes)
COLOR_SUCCESS = "#57AB5A"
COLOR_WARNING = "#D29922"
COLOR_ERROR = "#E5534B"
COLOR_MUTED = "#8B8E94"


@dataclass(frozen=True)
class Tokens:
    window: str
    base: str
    alt: str
    text: str
    subtext: str
    button: str
    border: str


DARK = Tokens(
    window="#1E1F22", base="#141517", alt="#1C1D20",
    text="#E6E6E8", subtext="#9A9DA3", button="#2A2C30", border="#3A3C40",
)
LIGHT = Tokens(
    window="#F4F4F5", base="#FFFFFF", alt="#EDEDEE",
    text="#1B1C1E", subtext="#6A6D73", button="#E8E8EA", border="#CFCFD4",
)
# red-on-black observatory mode: protects dark adaptation at the telescope
NIGHT = Tokens(
    window="#120404", base="#0A0202", alt="#1A0606",
    text="#D04040", subtext="#7A3030", button="#241010", border="#3A1414",
)


def tinted_icon(path, color: QColor) -> QIcon:
    """Recolor a monochrome icon to the given color (keeps the alpha shape).

    Used for the password eye icons so they stay visible on every theme's
    input background instead of baking in one fixed color.
    """
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return QIcon()
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), color)
    painter.end()
    return QIcon(pixmap)


def system_prefers_dark() -> bool:
    scheme = QGuiApplication.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Light:
        return False
    if scheme == Qt.ColorScheme.Dark:
        return True
    return True  # Unknown -> dark-first (astronomy tool)


def _build_palette(t: Tokens) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.window,
        QPalette.ColorRole.Base: t.base,
        QPalette.ColorRole.AlternateBase: t.alt,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.PlaceholderText: t.subtext,
        QPalette.ColorRole.Button: t.button,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.ToolTipBase: t.alt,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.Link: ACCENT_HOVER,
        QPalette.ColorRole.Mid: t.border,
        QPalette.ColorRole.Dark: t.border,
        QPalette.ColorRole.Light: t.alt,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    disabled = QColor(t.subtext)
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return palette


def _build_qss(t: Tokens) -> str:
    return f"""
    QPushButton#primary {{
        background: {ACCENT}; color: white; border: none; border-radius: 4px;
        padding: 8px 24px; font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
    QPushButton#primary:pressed {{ background: #C23237; }}
    QPushButton#primary:disabled {{ background: {t.button}; color: {t.subtext}; }}

    QFrame#planBanner {{
        background: rgba(222, 59, 64, 0.07);
        border: 1px solid rgba(222, 59, 64, 0.30);
        border-radius: 6px;
    }}
    QLabel#bannerHeadline {{ font-weight: 600; }}
    QLabel#warningsLabel {{ color: {COLOR_WARNING}; }}
    QLabel#errorLabel {{ color: {COLOR_ERROR}; }}
    QLabel#successLabel {{ color: {COLOR_SUCCESS}; }}
    QLabel#subtle {{ color: {t.subtext}; }}
    QLabel#emptyState {{ color: {t.subtext}; font-size: 15px; }}

    QPlainTextEdit#log {{
        font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px;
        background: {t.base}; border: none;
    }}

    QTableView {{
        gridline-color: {t.border};
        selection-background-color: rgba(222, 59, 64, 0.35);
        alternate-background-color: {t.alt};
    }}
    QHeaderView::section {{
        padding: 6px 8px; border: none; border-bottom: 1px solid {t.border};
        background: {t.window}; font-weight: 600;
    }}

    QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
        padding: 6px 8px; border: 1px solid {t.border}; border-radius: 4px;
        background: {t.base};
    }}
    QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
        border-color: {ACCENT};
    }}

    QStatusBar QLabel {{ padding: 0 8px; }}
    QProgressBar {{
        border: 1px solid {t.border}; border-radius: 4px; text-align: center;
        background: {t.base}; max-height: 14px;
    }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

    QToolTip {{ background: {t.alt}; color: {t.text}; border: 1px solid {t.border}; }}

    /* dropdown popups: explicit item colors so the hovered/selected entry is
       ALWAYS accent background + white text, never theme-dependent fallbacks
       (with a global stylesheet active, Qt otherwise falls back to the default
       palette for popup items: white-ish highlight + white text on light) */
    QComboBox QAbstractItemView {{
        background-color: {t.base}; color: {t.text}; border: 1px solid {t.border};
        selection-background-color: {ACCENT}; selection-color: #FFFFFF; outline: 0;
    }}
    QComboBox QAbstractItemView::item {{
        background-color: transparent; color: {t.text}; padding: 4px 8px;
        min-height: 22px;
    }}
    QComboBox QAbstractItemView::item:hover,
    QComboBox QAbstractItemView::item:selected {{
        background-color: {ACCENT}; color: #FFFFFF;
    }}
    QMenu {{ background-color: {t.window}; color: {t.text}; border: 1px solid {t.border}; }}
    QMenu::item {{ background-color: transparent; color: {t.text}; padding: 5px 24px 5px 12px; }}
    QMenu::item:selected {{ background-color: {ACCENT}; color: #FFFFFF; }}
    QMenu::item:disabled {{ color: {t.subtext}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 8px; }}

    QFrame#toastFrame {{
        background: {t.window}; border: 1px solid {t.border}; border-radius: 8px;
    }}
    QLabel#toastTitle {{ font-weight: 600; }}
    QToolButton#toastClose {{
        border: none; background: transparent; color: {t.subtext}; font-size: 14px;
    }}
    QToolButton#toastClose:hover {{ color: {t.text}; }}
    QPushButton#toastAction {{
        background: transparent; border: 1px solid {t.border}; border-radius: 4px;
        padding: 4px 10px;
    }}
    QPushButton#toastAction:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
    """


def apply_theme(app, mode: str = "system") -> bool:
    """Apply Fusion + palette + QSS. Returns True when a dark variant is active.

    Modes: 'system' | 'dark' | 'light' | 'night' (red-on-black observatory mode).
    """
    if mode == "night":
        tokens, dark = NIGHT, True
    else:
        dark = mode == "dark" or (mode == "system" and system_prefers_dark())
        tokens = DARK if dark else LIGHT
    app.setStyle("Fusion")
    app.setPalette(_build_palette(tokens))
    app.setStyleSheet(_build_qss(tokens))
    app.setProperty("darkTheme", dark)  # widgets (toast thumbnails) read this back
    return dark
