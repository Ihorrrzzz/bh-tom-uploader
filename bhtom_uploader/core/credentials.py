"""Secure credential storage via the OS keyring (Windows Credential Locker).

Replaces the legacy plaintext ``credentials.json``. On first use, a legacy file
found next to the project is imported once and deleted.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import keyring
import keyring.errors

from .settings import project_root

SERVICE = "bhtom-uploader"
LEGACY_FILE = "credentials.json"


class CredentialsError(Exception):
    """The OS keyring is unavailable or rejected the operation."""


def save_credentials(username: str, password: str) -> None:
    try:
        keyring.set_password(SERVICE, username, password)
    except keyring.errors.KeyringError as exc:
        raise CredentialsError(f"could not store credentials in the OS keyring: {exc}") from exc


def load_password(username: str) -> Optional[str]:
    if not username:
        return None
    try:
        return keyring.get_password(SERVICE, username)
    except keyring.errors.KeyringError:
        return None


def delete_credentials(username: str) -> None:
    try:
        keyring.delete_password(SERVICE, username)
    except keyring.errors.KeyringError:
        pass  # nothing stored - fine


def migrate_legacy_file(path: Optional[Path] = None) -> Optional[str]:
    """Import the old plaintext credentials.json once, then remove it.

    Returns the imported username, or None when there was nothing to migrate.
    """
    legacy = path or (project_root() / LEGACY_FILE)
    if not legacy.exists():
        return None
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
        username = data.get("username") or ""
        password = data.get("password") or ""
        if username and password:
            save_credentials(username, password)
        legacy.unlink()
        return username or None
    except (OSError, ValueError, CredentialsError):
        return None
