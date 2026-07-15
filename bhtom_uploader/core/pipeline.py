"""Pipeline: orchestrates calibrate -> upload for an approved scan.

Runs inside a QThread (``moveToThread`` + queued ``run`` slot); the UI listens
to signals only, so the GUI never blocks and the job survives minimize-to-tray.
The only Qt dependency in core is QtCore (QObject/Signal), per the architecture.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from .bhtom import BHTOMClient, BHTOMError, TargetMissingError
from .calibrator import CalibrationError, Calibrator
from .journal import UploadJournal
from .models import (
    PlannedAction,
    ScanResult,
    UploadItem,
    UploadStatus,
)


@dataclass
class RunOptions:
    """Everything the user chose in the UI for one run."""
    target: str
    observatory: str                     # ONAME (camera prefix)
    filter_name: str = "GaiaSP/any"
    dry_run: bool = False
    comment: str = ""
    observers: str = ""
    allow_raw: bool = False              # user explicitly confirmed raw upload
    output_dir: Optional[Path] = None    # default: <scan root>/Calibrated files


@dataclass
class RunReport:
    target: str
    items: list[UploadItem] = field(default_factory=list)
    cancelled: bool = False
    dry_run: bool = False

    @property
    def n_success(self) -> int:
        return sum(1 for i in self.items if i.status is UploadStatus.UPLOADED)

    @property
    def n_failed(self) -> int:
        return sum(1 for i in self.items if i.status is UploadStatus.FAILED)

    @property
    def n_skipped(self) -> int:
        return sum(1 for i in self.items if i.status is UploadStatus.SKIPPED)

    @property
    def dataproduct_ids(self) -> list[int]:
        ids: list[int] = []
        for item in self.items:
            ids.extend(item.dataproduct_ids)
        return ids

    def summary(self) -> str:
        parts = [f"{self.n_success} uploaded"]
        if self.n_failed:
            parts.append(f"{self.n_failed} failed")
        if self.n_skipped:
            parts.append(f"{self.n_skipped} skipped")
        if self.dry_run:
            parts.append("dry run - nothing stored")
        return ", ".join(parts)


class Pipeline(QObject):
    """One run over an approved ScanResult. Create fresh per run."""

    log = Signal(str)
    state_changed = Signal(str)          # "calibrating" | "uploading" | "done" | ...
    progress = Signal(int, int)          # done uploads, total uploads
    item_updated = Signal(object)        # UploadItem (same instance, mutated)
    finished = Signal(object)            # RunReport
    failed = Signal(str)                 # fatal, run aborted

    def __init__(
        self,
        scan: ScanResult,
        options: RunOptions,
        client: BHTOMClient,
        calibrator: Optional[Calibrator] = None,
        journal: Optional[UploadJournal] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.scan = scan
        self.options = options
        self.client = client
        self.journal = journal
        self.calibrator = calibrator or Calibrator(log=self.log.emit)
        if calibrator is not None:
            calibrator.log = self.log.emit
        self._cancelled = False
        self._paused = False

    # -- control (callable from the UI thread; plain flags, checked between units)
    def cancel(self) -> None:
        self._cancelled = True
        self._paused = False

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.log.emit("paused" if paused else "resumed")

    def _wait_if_paused(self) -> None:
        while self._paused and not self._cancelled:
            time.sleep(0.2)

    # ------------------------------------------------------------------
    @Slot()
    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:  # never let a worker thread die silently
            self.failed.emit(f"unexpected pipeline error: {exc}")

    def _run(self) -> None:
        opts = self.options
        report = RunReport(target=opts.target, dry_run=opts.dry_run)
        out_dir = Path(opts.output_dir) if opts.output_dir else (self.scan.root / "Calibrated files")

        # -- build the work list group by group
        work: list[UploadItem] = []
        for group in self.scan.light_groups:
            if group.action is PlannedAction.SKIP:
                continue
            if group.action is PlannedAction.UPLOAD_RAW_CONFIRM and not opts.allow_raw:
                for frame in group.frames:
                    item = UploadItem(frame.path, frame.path, opts.target,
                                      status=UploadStatus.SKIPPED,
                                      message="raw upload not confirmed")
                    report.items.append(item)
                    self.item_updated.emit(item)
                self.log.emit(f"{group.display_name}: skipped (raw upload not confirmed)")
                continue

            # journal dedup: frames already uploaded to this target are skipped
            # BEFORE calibration (watch mode / re-runs must not duplicate data)
            if self.journal is not None:
                fresh = []
                for frame in group.frames:
                    if self.journal.already_uploaded(frame.path, opts.target):
                        item = UploadItem(frame.path, frame.path, opts.target,
                                          status=UploadStatus.SKIPPED,
                                          message="already uploaded to this target (journal)")
                        report.items.append(item)
                        self.item_updated.emit(item)
                    else:
                        fresh.append(frame)
                if not fresh:
                    self.log.emit(f"{group.display_name}: all frames already uploaded - skipped")
                    continue
                if len(fresh) != len(group.frames):
                    self.log.emit(
                        f"{group.display_name}: {len(group.frames) - len(fresh)} frame(s) "
                        "already uploaded - skipped (journal)"
                    )
                    group = replace(group, frames=fresh)

            if group.action is PlannedAction.CALIBRATE_THEN_UPLOAD:
                self.state_changed.emit("calibrating")
                self.log.emit(f"calibrating {group.display_name} ({group.n_raw} raw frame(s))")
                calib = self.scan.calibration_for(group)
                try:
                    pairs = self.calibrator.calibrate_group(group, calib, out_dir)
                except CalibrationError as exc:
                    self.log.emit(f"calibration failed for {group.display_name}: {exc}")
                    for frame in group.frames:
                        item = UploadItem(frame.path, frame.path, opts.target,
                                          status=UploadStatus.FAILED,
                                          message=f"calibration failed: {exc}")
                        report.items.append(item)
                        self.item_updated.emit(item)
                    continue
            else:  # UPLOAD_DIRECT or confirmed raw
                pairs = [(frame, frame.path, "as-is") for frame in group.frames]

            for frame, upload_path, note in pairs:
                item = UploadItem(frame.path, Path(upload_path), opts.target)
                item.message = note
                report.items.append(item)
                self.item_updated.emit(item)

            if self._cancelled:
                break

        # -- upload
        pending = [i for i in report.items if i.status is UploadStatus.PENDING]
        total = len(pending)
        self.state_changed.emit("uploading")
        self.log.emit(
            f"uploading {total} file(s) to target '{opts.target}' "
            f"as observatory '{opts.observatory}'"
            + (" [DRY RUN]" if opts.dry_run else "")
        )
        done = 0
        self.progress.emit(done, total)
        for item in pending:
            self._wait_if_paused()
            if self._cancelled:
                item.status = UploadStatus.SKIPPED
                item.message = "cancelled"
                self.item_updated.emit(item)
                continue
            item.status = UploadStatus.UPLOADING
            self.item_updated.emit(item)
            try:
                ids, payload = self.client.upload_fits(
                    item.upload_path,
                    target=opts.target,
                    observatory=opts.observatory,
                    filter_name=opts.filter_name,
                    dry_run=opts.dry_run,
                    comment=opts.comment or None,
                    observers=opts.observers or None,
                )
                item.dataproduct_ids = ids
                item.status = UploadStatus.UPLOADED
                item.message = self._success_message(payload) or "accepted"
                if self.journal is not None and not opts.dry_run:
                    self.journal.record(item.source, opts.target, ids)
                self.log.emit(f"uploaded {item.name} (id {', '.join(map(str, ids)) or 'n/a'})")
            except TargetMissingError as exc:
                # UI pre-checks the target, so this is fatal (e.g. deleted mid-run)
                item.status = UploadStatus.FAILED
                item.message = str(exc)
                self.item_updated.emit(item)
                self.failed.emit(str(exc))
                return
            except BHTOMError as exc:
                item.status = UploadStatus.FAILED
                item.message = str(exc)
                self.log.emit(f"upload failed for {item.name}: {exc}")
            done += 1
            self.progress.emit(done, total)
            self.item_updated.emit(item)

        report.cancelled = self._cancelled
        self.state_changed.emit("cancelled" if self._cancelled else "done")
        self.log.emit(f"run finished: {report.summary()}")
        self.finished.emit(report)

    @staticmethod
    def _success_message(payload: dict) -> str:
        """Pull the per-file message out of the verified live response shape."""
        success = payload.get("Success") if isinstance(payload, dict) else None
        if isinstance(success, list) and success and isinstance(success[0], dict):
            return str(success[0].get("message") or "")
        return ""
