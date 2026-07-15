"""Configuration: service URLs from config.ini + user preferences via QSettings.

URL config keeps the existing ``config.ini`` pattern (section ``[API]``) so a
future BHTOM domain move stays a one-line change. User preferences live in
QSettings (registry on Windows); Qt is imported lazily so pure-core code and
tests can import this module without the GUI stack.
"""
from __future__ import annotations

import configparser
import sys
from pathlib import Path
from typing import Any, Optional

DEFAULT_BHTOM_URL = "https://bh-tom2.astrouw.edu.pl"
DEFAULT_UPLOAD_URL = "https://uploadsvc2.bh-tom2.astrouw.edu.pl"
DEFAULT_FILTER = "GaiaSP/any"

_ORG = "BHTOM"
_APP = "BHTOM Uploader"


def project_root() -> Path:
    """Folder containing config.ini: exe dir when frozen, repo root otherwise."""
    if getattr(sys, "frozen", False):  # PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _read_config() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(project_root() / "config.ini")
    return parser


def get_bhtom_url() -> str:
    return _read_config().get("API", "bhtom_url", fallback=DEFAULT_BHTOM_URL).rstrip("/")


def get_upload_url() -> str:
    return _read_config().get("API", "upload_url", fallback=DEFAULT_UPLOAD_URL).rstrip("/")


class Settings:
    """Typed accessors over QSettings for everything the UI can configure."""

    def __init__(self) -> None:
        from PySide6.QtCore import QSettings  # lazy: keep core importable without Qt

        self._qs = QSettings(_ORG, _APP)

    # -- generic helpers ------------------------------------------------
    def _get(self, key: str, default: Any = None) -> Any:
        return self._qs.value(key, default)

    def _get_bool(self, key: str, default: bool) -> bool:
        value = self._qs.value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "yes")

    def _get_float(self, key: str, default: Optional[float]) -> Optional[float]:
        value = self._qs.value(key, default)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _set(self, key: str, value: Any) -> None:
        self._qs.setValue(key, value)

    # -- upload defaults -------------------------------------------------
    @property
    def observatory_oname(self) -> str:
        return str(self._get("upload/observatory_oname", "") or "")

    @observatory_oname.setter
    def observatory_oname(self, value: str) -> None:
        self._set("upload/observatory_oname", value)

    @property
    def filter_name(self) -> str:
        return str(self._get("upload/filter", DEFAULT_FILTER) or DEFAULT_FILTER)

    @filter_name.setter
    def filter_name(self, value: str) -> None:
        self._set("upload/filter", value)

    @property
    def last_target(self) -> str:
        return str(self._get("upload/last_target", "") or "")

    @last_target.setter
    def last_target(self, value: str) -> None:
        self._set("upload/last_target", value)

    @property
    def dry_run(self) -> bool:
        return self._get_bool("upload/dry_run", False)

    @dry_run.setter
    def dry_run(self, value: bool) -> None:
        self._set("upload/dry_run", bool(value))

    @property
    def observers(self) -> str:
        return str(self._get("upload/observers", "") or "")

    @observers.setter
    def observers(self, value: str) -> None:
        self._set("upload/observers", value)

    @property
    def comment(self) -> str:
        return str(self._get("upload/comment", "") or "")

    @comment.setter
    def comment(self, value: str) -> None:
        self._set("upload/comment", value)

    # -- calibration -----------------------------------------------------
    @property
    def flat_min_adu(self) -> Optional[float]:
        return self._get_float("calibration/flat_min_adu", None)

    @flat_min_adu.setter
    def flat_min_adu(self, value: Optional[float]) -> None:
        self._set("calibration/flat_min_adu", "" if value is None else value)

    @property
    def flat_max_adu(self) -> Optional[float]:
        return self._get_float("calibration/flat_max_adu", None)

    @flat_max_adu.setter
    def flat_max_adu(self, value: Optional[float]) -> None:
        self._set("calibration/flat_max_adu", "" if value is None else value)

    @property
    def cosmic_ray(self) -> bool:
        return self._get_bool("calibration/cosmic_ray", False)

    @cosmic_ray.setter
    def cosmic_ray(self, value: bool) -> None:
        self._set("calibration/cosmic_ray", bool(value))

    @property
    def saturation_adu(self) -> Optional[float]:
        """Manual saturation level override; None = use the FITS SATURATE keyword."""
        return self._get_float("calibration/saturation_adu", None)

    @saturation_adu.setter
    def saturation_adu(self, value: Optional[float]) -> None:
        self._set("calibration/saturation_adu", "" if value is None else value)

    # -- UI behavior -------------------------------------------------------
    @property
    def theme(self) -> str:
        """'system' | 'dark' | 'light'."""
        return str(self._get("ui/theme", "system") or "system")

    @theme.setter
    def theme(self, value: str) -> None:
        self._set("ui/theme", value)

    @property
    def minimize_to_tray(self) -> bool:
        return self._get_bool("ui/minimize_to_tray", True)

    @minimize_to_tray.setter
    def minimize_to_tray(self, value: bool) -> None:
        self._set("ui/minimize_to_tray", bool(value))

    @property
    def username(self) -> str:
        """Last logged-in username (NOT the password - that lives in keyring)."""
        return str(self._get("auth/username", "") or "")

    @username.setter
    def username(self, value: str) -> None:
        self._set("auth/username", value)

    def save_geometry(self, name: str, data: bytes) -> None:
        self._set(f"geometry/{name}", data)

    def load_geometry(self, name: str):
        return self._get(f"geometry/{name}")
