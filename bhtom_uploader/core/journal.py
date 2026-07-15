"""Upload journal: prevents duplicate uploads (watch mode + across restarts).

Keyed by (resolved source path, size, mtime) - a re-exported or modified file
counts as new. Only *successful* uploads are recorded, so retrying failures
stays possible. Stored as JSON under %LOCALAPPDATA%/BHTOM/BHTOM Uploader.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def default_journal_path() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "BHTOM" / "BHTOM Uploader" / "upload_journal.json"


class UploadJournal:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else default_journal_path()
        self._data: dict[str, dict] = {}
        self._load()

    @staticmethod
    def _key(path: Path) -> Optional[str]:
        try:
            stat = Path(path).stat()
        except OSError:
            return None
        return f"{Path(path).resolve()}|{stat.st_size}|{int(stat.st_mtime)}"

    def _load(self) -> None:
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self._data, dict):
                self._data = {}
        except (OSError, ValueError):
            self._data = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass  # journal is best-effort; never break an upload over it

    # ------------------------------------------------------------------
    def already_uploaded(self, source: Path, target: str) -> bool:
        key = self._key(source)
        record = self._data.get(key) if key else None
        return bool(record and record.get("target", "").lower() == target.lower())

    def record(self, source: Path, target: str, ids: list[int]) -> None:
        key = self._key(source)
        if not key:
            return
        self._data[key] = {
            "target": target,
            "ids": list(ids),
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "name": Path(source).name,
        }
        self._save()
