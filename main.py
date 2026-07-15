"""BHTOM Uploader - entry point (PyCharm run config + frozen exe target)."""
import sys


def _smoke() -> int:
    """Self-check for the frozen build: boots Qt + theme + login UI offscreen.

    Writes the result to smoke_result.txt (a --windowed exe has no console).
    """
    import os
    from pathlib import Path

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines = []
    try:
        import keyring
        from PySide6.QtWidgets import QApplication

        from bhtom_uploader import __version__
        from bhtom_uploader.core.bhtom import BHTOMClient
        from bhtom_uploader.core.settings import Settings, get_bhtom_url
        from bhtom_uploader.ui.login_window import LoginDialog
        from bhtom_uploader.ui.theme import apply_theme

        app = QApplication([])
        apply_theme(app, "dark")
        LoginDialog(BHTOMClient(), Settings())
        backend = type(keyring.get_keyring()).__name__
        lines.append(f"SMOKE OK v{__version__}")
        lines.append(f"keyring backend: {backend}")
        lines.append(f"bhtom url: {get_bhtom_url()}")
        code = 0 if backend == "WinVaultKeyring" else 2  # plaintext fallback would be 2
    except Exception as exc:  # noqa: BLE001 - report anything
        lines.append(f"SMOKE FAILED: {type(exc).__name__}: {exc}")
        code = 1
    Path("smoke_result.txt").write_text("\n".join(lines), encoding="utf-8")
    return code


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        raise SystemExit(_smoke())
    from bhtom_uploader.app import run

    raise SystemExit(run())
