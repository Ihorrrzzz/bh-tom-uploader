"""Core data models shared by the scanner, calibrator, pipeline and UI."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class FrameType(enum.Enum):
    """Astronomical frame kind, per FITS IMAGETYP conventions."""
    LIGHT = "light"
    BIAS = "bias"
    DARK = "dark"
    FLAT = "flat"
    UNKNOWN = "unknown"


class Confidence(enum.Enum):
    HIGH = "high"   # explicit IMAGETYP match
    LOW = "low"     # inferred from filename / other keywords - user should verify


class CalibrationState(enum.Enum):
    """Whether a light frame has already been bias/dark/flat corrected."""
    CALIBRATED = "calibrated"
    RAW = "raw"
    NOT_APPLICABLE = "n/a"  # calibration frames and unknown files


class PlannedAction(enum.Enum):
    """What the pipeline intends to do with a light group."""
    UPLOAD_DIRECT = "upload"                    # already calibrated -> upload as-is
    CALIBRATE_THEN_UPLOAD = "calibrate+upload"  # raw lights + calibration set available
    UPLOAD_RAW_CONFIRM = "confirm-raw"          # raw lights, no calibration set -> explicit user confirmation
    SKIP = "skip"                               # calibration frames / unknown files


class UploadStatus(enum.Enum):
    PENDING = "pending"
    CALIBRATING = "calibrating"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"       # accepted by the upload service, awaiting server calibration
    POLLING = "polling"         # waiting for BHTOM standardisation verdict
    SUCCESS = "success"         # server produced a photometry point (or limit)
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class FrameInfo:
    """One FITS file: parsed header metadata + classification verdicts."""
    path: Path
    frame_type: FrameType = FrameType.UNKNOWN
    confidence: Confidence = Confidence.LOW
    calibration_state: CalibrationState = CalibrationState.NOT_APPLICABLE
    calibration_evidence: str = ""  # human-readable reason for the calibrated/raw verdict
    object_name: Optional[str] = None
    filter_name: Optional[str] = None
    exptime: Optional[float] = None
    binning: Optional[tuple[int, int]] = None
    ccd_temp: Optional[float] = None
    date_obs: Optional[str] = None
    ra: Optional[float] = None      # degrees
    dec: Optional[float] = None     # degrees
    shape: Optional[tuple[int, int]] = None  # (NAXIS2, NAXIS1)
    error: Optional[str] = None     # set when the file could not be read

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def stack_key(self) -> tuple:
        """Frames may only be stacked/calibrated together when this key matches."""
        return (self.shape, self.binning)


@dataclass
class CalibrationSet:
    """Calibration frames available for one (shape, binning) configuration."""
    biases: list[FrameInfo] = field(default_factory=list)
    darks: list[FrameInfo] = field(default_factory=list)  # mixed exposures allowed (scaled at use)
    flats_by_filter: dict[str, list[FrameInfo]] = field(default_factory=dict)

    @property
    def has_bias(self) -> bool:
        return bool(self.biases)

    @property
    def has_dark(self) -> bool:
        return bool(self.darks)

    def flats_for(self, filter_name: Optional[str]) -> list[FrameInfo]:
        return self.flats_by_filter.get(filter_name or "", [])

    @property
    def is_empty(self) -> bool:
        return not (self.biases or self.darks or self.flats_by_filter)

    def describe(self) -> str:
        parts = []
        if self.biases:
            parts.append(f"{len(self.biases)} bias")
        if self.darks:
            parts.append(f"{len(self.darks)} dark")
        for filt, flats in sorted(self.flats_by_filter.items()):
            parts.append(f"{len(flats)} flat [{filt or 'no filter'}]")
        return ", ".join(parts) if parts else "no calibration frames"


@dataclass
class LightGroup:
    """Light frames grouped by (object, filter, stack configuration)."""
    object_name: Optional[str]
    filter_name: Optional[str]
    stack_key: tuple
    frames: list[FrameInfo] = field(default_factory=list)
    action: PlannedAction = PlannedAction.SKIP
    reason: str = ""

    @property
    def n_calibrated(self) -> int:
        return sum(1 for f in self.frames if f.calibration_state is CalibrationState.CALIBRATED)

    @property
    def n_raw(self) -> int:
        return sum(1 for f in self.frames if f.calibration_state is CalibrationState.RAW)

    @property
    def display_name(self) -> str:
        obj = self.object_name or "(no OBJECT)"
        filt = self.filter_name or "no filter"
        return f"{obj} [{filt}]"


@dataclass
class ScanResult:
    """Everything the scanner learned about a folder / file selection."""
    root: Path
    frames: list[FrameInfo] = field(default_factory=list)
    light_groups: list[LightGroup] = field(default_factory=list)
    calibration_sets: dict[tuple, CalibrationSet] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def frames_of(self, frame_type: FrameType) -> list[FrameInfo]:
        return [f for f in self.frames if f.frame_type is frame_type]

    def calibration_for(self, group: LightGroup) -> CalibrationSet:
        return self.calibration_sets.get(group.stack_key, CalibrationSet())

    @property
    def unreadable(self) -> list[FrameInfo]:
        return [f for f in self.frames if f.error]

    @property
    def needs_confirmation(self) -> bool:
        """True when the plan includes uploading raw frames (user must explicitly confirm)."""
        return any(g.action is PlannedAction.UPLOAD_RAW_CONFIRM for g in self.light_groups)

    def summary(self) -> str:
        """One-line human summary, e.g. '12 lights (3 raw), 15 bias, 10 dark, 20 flat'."""
        lights = self.frames_of(FrameType.LIGHT)
        parts = []
        if lights:
            raw = sum(1 for f in lights if f.calibration_state is CalibrationState.RAW)
            parts.append(f"{len(lights)} light" + (f" ({raw} raw)" if raw else " (all calibrated)"))
        for ft in (FrameType.BIAS, FrameType.DARK, FrameType.FLAT):
            n = len(self.frames_of(ft))
            if n:
                parts.append(f"{n} {ft.value}")
        n_unknown = len(self.frames_of(FrameType.UNKNOWN))
        if n_unknown:
            parts.append(f"{n_unknown} unknown")
        return ", ".join(parts) if parts else "no FITS frames found"


@dataclass
class CalibVerdict:
    """BHTOM server-side standardisation result for one uploaded file."""
    calib_id: Optional[int] = None
    status: str = ""            # raw status string from the server
    mag: Optional[float] = None
    mag_err: Optional[float] = None
    zp_error: Optional[float] = None
    is_limit: bool = False      # mag_err == -1 convention: limiting magnitude
    message: str = ""
    raw: dict = field(default_factory=dict)  # full server record for the detail pane


@dataclass
class UploadItem:
    """One file travelling through the upload pipeline."""
    source: Path                    # original frame on disk
    upload_path: Path               # what is actually sent (calibrated output or the source)
    target: str
    status: UploadStatus = UploadStatus.PENDING
    message: str = ""
    dataproduct_ids: list[int] = field(default_factory=list)
    verdict: Optional[CalibVerdict] = None

    @property
    def name(self) -> str:
        return self.upload_path.name
