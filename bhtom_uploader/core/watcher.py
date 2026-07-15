"""Folder watcher: watchdog + stable-file detection for FITS being written.

Acquisition software writes FITS incrementally (or writes a temp name and
renames), so filesystem events fire before a file is complete. A file is
emitted via ``file_ready`` only when its size+mtime were unchanged across
consecutive sweeps AND astropy can open it. ``FileClosedEvent`` is Linux-only
and deliberately not used.

watchdog callbacks arrive on the observer thread; they only touch a
lock-guarded pending dict. The sweep timer runs on the Qt thread and is the
only emitter of signals.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from astropy.io import fits
from PySide6.QtCore import QObject, QTimer, Signal
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .scanner import EXCLUDED_DIR_NAMES, is_fits_name

MAX_OPEN_ATTEMPTS = 20  # sweeps a stable-size file may fail astropy open before we give up


class _Handler(FileSystemEventHandler):
    def __init__(self, callback) -> None:
        self._callback = callback

    def on_created(self, event) -> None:
        if not event.is_directory:
            self._callback(event.src_path)

    def on_modified(self, event) -> None:
        if not event.is_directory:
            self._callback(event.src_path)

    def on_moved(self, event) -> None:
        # temp-name -> final-name rename is a common "write finished" signal
        if not event.is_directory:
            self._callback(event.dest_path)


class FolderWatcher(QObject):
    file_ready = Signal(object)   # Path - stable and readable
    watch_error = Signal(str)

    def __init__(
        self,
        folder: Path,
        parent: Optional[QObject] = None,
        stable_checks: int = 2,
        interval_ms: int = 1500,
    ) -> None:
        super().__init__(parent)
        self.folder = Path(folder)
        self.stable_checks = stable_checks
        self._lock = threading.Lock()
        self._pending: dict[str, list[tuple[int, int]]] = {}   # path -> [(size, mtime), ...]
        self._attempts: dict[str, int] = {}
        self._observer: Optional[Observer] = None
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._sweep)

    # ------------------------------------------------------------------
    def start(self) -> None:
        handler = _Handler(self._on_fs_event)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.folder), recursive=True)
        self._observer.daemon = True
        self._observer.start()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
        with self._lock:
            self._pending.clear()
            self._attempts.clear()

    # ------------------------------------------------------------------
    def _relevant(self, path: Path) -> bool:
        if not is_fits_name(path.name):
            return False
        try:
            parts = path.relative_to(self.folder).parts[:-1]
        except ValueError:
            return False
        lowered = {p.lower() for p in parts}
        if lowered & EXCLUDED_DIR_NAMES:
            return False  # our own calibration outputs
        return not any(p.startswith(".") for p in parts)

    def _on_fs_event(self, path_str: str) -> None:
        """Runs on the watchdog observer thread - collect only."""
        path = Path(path_str)
        if not self._relevant(path):
            return
        with self._lock:
            self._pending.setdefault(str(path), [])

    def _sweep(self) -> None:
        """Runs on the Qt thread: promote stable+readable files to file_ready."""
        with self._lock:
            paths = list(self._pending.keys())
        for path_str in paths:
            path = Path(path_str)
            try:
                stat = path.stat()
            except OSError:
                self._drop(path_str)   # vanished (temp file renamed away, etc.)
                continue
            with self._lock:
                history = self._pending.setdefault(path_str, [])
                history.append((stat.st_size, int(stat.st_mtime)))
                del history[: -(self.stable_checks + 1)]
                stable = (
                    len(history) > self.stable_checks
                    and len(set(history[-(self.stable_checks + 1):])) == 1
                    and stat.st_size > 0
                )
            if not stable:
                continue
            if self._openable(path):
                self._drop(path_str)
                self.file_ready.emit(path)
            else:
                attempts = self._attempts.get(path_str, 0) + 1
                self._attempts[path_str] = attempts
                if attempts >= MAX_OPEN_ATTEMPTS:
                    self._drop(path_str)
                    self.watch_error.emit(f"{path.name}: file never became readable - ignored")

    def _drop(self, path_str: str) -> None:
        with self._lock:
            self._pending.pop(path_str, None)
        self._attempts.pop(path_str, None)

    @staticmethod
    def _openable(path: Path) -> bool:
        try:
            with fits.open(path, memmap=True):
                return True
        except Exception:
            return False
