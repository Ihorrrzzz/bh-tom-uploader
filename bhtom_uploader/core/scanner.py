"""FITS discovery, header parsing, frame classification and upload planning.

Classification decision table (priority order):
1. ``IMAGETYP`` header keyword (case-insensitive substring match) -> HIGH confidence.
2. Fallbacks (LOW confidence, shown as "unverified" in the UI for user override):
   filename tokens, then ``OBJECT`` keyword presence + exposure time.

Calibrated-vs-raw detection for light frames reads provenance we or common
software wrote: ``CALSTAT`` (MaxIm-style), ``HISTORY``/``COMMENT`` markers
(including our own ``BHTOM-UPLOADER`` marker and ccdproc signatures), and
filename conventions (``calibrated_*`` from this app, ``-b/-bd/-bdf`` suffixes
from the author's calib-fits pipeline).
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

from astropy.coordinates import Angle
from astropy.io import fits
from astropy import units as u

from .models import (
    CalibrationSet,
    CalibrationState,
    Confidence,
    FrameInfo,
    FrameType,
    LightGroup,
    PlannedAction,
    ScanResult,
)

FITS_EXTENSIONS = {".fits", ".fit", ".fts"}

#: Folder names never scanned (our own outputs / master frames).
EXCLUDED_DIR_NAMES = {"calibrated files", "masters"}

#: CCD temperature spread within one stack that triggers a warning (deg C).
TEMP_SPREAD_WARN = 5.0

# --- IMAGETYP decision table (checked in order; substring match on upper) ---
# DARK before FLAT so "Dark Flat"/"FLATDARK" classifies as dark.
_IMAGETYP_TOKENS: list[tuple[str, FrameType]] = [
    ("BIAS", FrameType.BIAS),
    ("ZERO", FrameType.BIAS),
    ("DARK", FrameType.DARK),
    ("FLAT", FrameType.FLAT),
    ("LIGHT", FrameType.LIGHT),
    ("SCIENCE", FrameType.LIGHT),
    ("OBJECT", FrameType.LIGHT),
]

_FILENAME_TOKENS: list[tuple[str, FrameType]] = [
    ("bias", FrameType.BIAS),
    ("zero", FrameType.BIAS),
    ("dark", FrameType.DARK),
    ("flat", FrameType.FLAT),
    ("light", FrameType.LIGHT),
]

# --- markers meaning "this light frame is already calibrated" ---
_CALIBRATED_MARKERS = (
    "bhtom-uploader",        # our own provenance line
    "calibrat",              # "calibrated", "calibration applied", ...
    "bias subtracted",
    "subtract_bias",         # ccdproc keyword/history signatures
    "dark subtracted",
    "subtract_dark",
    "flat field",
    "flat-field",
    "flatfield",
    "flat_correct",
    "ccd_process",
)

#: filename endings written by the author's calib-fits pipeline
_CALIBFITS_SUFFIX_RE = re.compile(r"-(b|bd|bdf)$", re.IGNORECASE)


# --------------------------------------------------------------------------
# Header helpers
# --------------------------------------------------------------------------

def _get_float(header: fits.Header, *keys: str) -> Optional[float]:
    for key in keys:
        if key in header:
            try:
                return float(header[key])
            except (TypeError, ValueError):
                continue
    return None


def _get_str(header: fits.Header, *keys: str) -> Optional[str]:
    for key in keys:
        value = header.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return None


def _parse_angle(value, hourangle: bool) -> Optional[float]:
    """Parse an RA/DEC header value (float degrees or sexagesimal string) to degrees."""
    if value is None:
        return None
    try:
        return float(value)  # numeric header values are already in degrees
    except (TypeError, ValueError):
        pass
    try:
        unit = u.hourangle if hourangle else u.deg
        return float(Angle(str(value), unit=unit).to(u.deg).value)
    except Exception:
        return None


def extract_ra_dec(header: fits.Header) -> tuple[Optional[float], Optional[float]]:
    """RA/DEC in degrees from common header keywords, falling back to WCS reference."""
    ra = _parse_angle(header.get("RA"), hourangle=isinstance(header.get("RA"), str))
    dec = _parse_angle(header.get("DEC"), hourangle=False)
    if ra is None:
        ra = _parse_angle(header.get("OBJCTRA"), hourangle=True)
    if dec is None:
        dec = _parse_angle(header.get("OBJCTDEC"), hourangle=False)
    if ra is None:
        ra = _get_float(header, "CRVAL1")
    if dec is None:
        dec = _get_float(header, "CRVAL2")
    return ra, dec


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

def classify_frame_type(header: fits.Header, path: Path) -> tuple[FrameType, Confidence]:
    imagetyp = _get_str(header, "IMAGETYP", "IMGTYPE", "FRAMETYP", "OBSTYPE")
    if imagetyp:
        upper = imagetyp.upper()
        for token, frame_type in _IMAGETYP_TOKENS:
            if token in upper:
                return frame_type, Confidence.HIGH

    # Fallback 1: filename tokens
    lower_name = path.stem.lower()
    for token, frame_type in _FILENAME_TOKENS:
        if token in lower_name:
            return frame_type, Confidence.LOW

    # Fallback 2: an OBJECT keyword with a real exposure smells like a light frame
    if _get_str(header, "OBJECT") and (_get_float(header, "EXPTIME", "EXPOSURE") or 0) > 0:
        return FrameType.LIGHT, Confidence.LOW

    return FrameType.UNKNOWN, Confidence.LOW


def detect_calibration_state(header: fits.Header, path: Path) -> tuple[CalibrationState, str]:
    """Decide whether a *light* frame is already calibrated, with evidence."""
    calstat = _get_str(header, "CALSTAT")
    if calstat and any(ch in calstat.upper() for ch in "BDF"):
        return CalibrationState.CALIBRATED, f"CALSTAT={calstat}"

    # HISTORY / COMMENT provenance markers
    for card_type in ("HISTORY", "COMMENT"):
        if card_type in header:
            text = " ".join(str(v) for v in header[card_type]).lower()
            for marker in _CALIBRATED_MARKERS:
                if marker in text:
                    return CalibrationState.CALIBRATED, f"{card_type} contains '{marker}'"

    # ccdproc writes operation keywords onto processed frames
    for kw in ("SUBBIAS", "SUBDARK", "FLATCOR"):
        if kw in header:
            return CalibrationState.CALIBRATED, f"header keyword {kw}"

    # Filename conventions: our old output prefix, calib-fits suffixes
    stem = path.stem
    if stem.lower().startswith("calibrated_"):
        return CalibrationState.CALIBRATED, "filename prefix 'calibrated_'"
    if _CALIBFITS_SUFFIX_RE.search(stem):
        return CalibrationState.CALIBRATED, f"calib-fits filename suffix '{stem[stem.rfind('-'):]}'"

    return CalibrationState.RAW, "no calibration provenance found"


def read_frame_info(path: Path) -> FrameInfo:
    """Parse one FITS file into a FrameInfo (never raises; errors are recorded)."""
    info = FrameInfo(path=path)
    try:
        with fits.open(path, memmap=True) as hdul:
            header = hdul[0].header
            # data shape from header only - avoid loading pixels during a scan
            naxis1, naxis2 = header.get("NAXIS1"), header.get("NAXIS2")
            if naxis1 and naxis2:
                info.shape = (int(naxis2), int(naxis1))
    except Exception as exc:  # corrupt / truncated / not really FITS
        info.error = f"unreadable: {exc}"
        return info

    info.frame_type, info.confidence = classify_frame_type(header, path)
    info.object_name = _get_str(header, "OBJECT")
    info.filter_name = _get_str(header, "FILTER", "FILTER1", "FILTERS")
    info.exptime = _get_float(header, "EXPTIME", "EXPOSURE")
    xbin = _get_float(header, "XBINNING", "XBIN", "CCDXBIN")
    ybin = _get_float(header, "YBINNING", "YBIN", "CCDYBIN")
    if xbin and ybin:
        info.binning = (int(xbin), int(ybin))
    info.ccd_temp = _get_float(header, "CCD-TEMP", "CCDTEMP", "SET-TEMP")
    info.date_obs = _get_str(header, "DATE-OBS", "DATE")
    info.ra, info.dec = extract_ra_dec(header)

    if info.frame_type is FrameType.LIGHT:
        info.calibration_state, info.calibration_evidence = detect_calibration_state(header, path)
    return info


# --------------------------------------------------------------------------
# Discovery + grouping + planning
# --------------------------------------------------------------------------

def find_fits_files(root: Path, recursive: bool = True) -> list[Path]:
    """All FITS files under root, skipping our own output folders."""
    results: list[Path] = []
    if root.is_file():
        return [root] if root.suffix.lower() in FITS_EXTENSIONS else []
    for path in sorted(root.rglob("*") if recursive else root.glob("*")):
        if path.is_dir():
            continue
        if path.suffix.lower() not in FITS_EXTENSIONS:
            continue
        rel_parts = {p.lower() for p in path.relative_to(root).parts[:-1]}
        if rel_parts & EXCLUDED_DIR_NAMES:
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        results.append(path)
    return results


def scan_paths(paths: Iterable[Path], root: Path) -> ScanResult:
    """Parse + classify a set of FITS files and build the upload plan."""
    frames = [read_frame_info(Path(p)) for p in paths]
    return build_scan_result(frames, Path(root))


def build_scan_result(frames: list[FrameInfo], root: Path) -> ScanResult:
    """Group frames + plan actions. Public so the UI can re-plan after the user
    overrides a frame type in the table (frames are reused, files not re-read)."""
    result = ScanResult(root=Path(root), frames=frames)

    readable = [f for f in frames if not f.error]
    for bad in (f for f in frames if f.error):
        result.warnings.append(f"{bad.name}: {bad.error}")

    # -- calibration sets, keyed by stack configuration (shape, binning)
    for frame in readable:
        if frame.frame_type in (FrameType.BIAS, FrameType.DARK, FrameType.FLAT):
            calib = result.calibration_sets.setdefault(frame.stack_key, CalibrationSet())
            if frame.frame_type is FrameType.BIAS:
                calib.biases.append(frame)
            elif frame.frame_type is FrameType.DARK:
                calib.darks.append(frame)
            else:
                calib.flats_by_filter.setdefault(frame.filter_name or "", []).append(frame)

    # -- light groups by (object, filter, stack configuration)
    grouped: dict[tuple, LightGroup] = {}
    for frame in readable:
        if frame.frame_type is not FrameType.LIGHT:
            continue
        key = (frame.object_name, frame.filter_name, frame.stack_key)
        group = grouped.get(key)
        if group is None:
            group = grouped[key] = LightGroup(
                object_name=frame.object_name,
                filter_name=frame.filter_name,
                stack_key=frame.stack_key,
            )
        group.frames.append(frame)
    result.light_groups = list(grouped.values())

    _plan_actions(result)
    _collect_warnings(result)
    return result


def scan_directory(root: Path, recursive: bool = True) -> ScanResult:
    root = Path(root)
    return scan_paths(find_fits_files(root, recursive=recursive), root=root)


def _plan_actions(result: ScanResult) -> None:
    """Assign a PlannedAction to every light group (the user-visible plan)."""
    for group in result.light_groups:
        calib = result.calibration_for(group)
        if group.n_raw == 0:
            group.action = PlannedAction.UPLOAD_DIRECT
            group.reason = "all frames already calibrated"
        elif not calib.is_empty:
            group.action = PlannedAction.CALIBRATE_THEN_UPLOAD
            usable = calib.describe()
            group.reason = f"{group.n_raw} raw frame(s); will calibrate using {usable}"
            if group.n_calibrated:
                group.reason += f"; {group.n_calibrated} already-calibrated frame(s) upload as-is"
            if not calib.flats_for(group.filter_name) and calib.flats_by_filter:
                group.reason += f" (no flats for filter '{group.filter_name or ''}')"
        else:
            group.action = PlannedAction.UPLOAD_RAW_CONFIRM
            group.reason = (
                "raw frames with no calibration frames in the selection - "
                "uploading raw files is not recommended"
            )


def _collect_warnings(result: ScanResult) -> None:
    # CCD temperature spread inside each calibration stack
    for key, calib in result.calibration_sets.items():
        stacks = [("bias", calib.biases), ("dark", calib.darks)]
        stacks += [(f"flat[{filt or 'no filter'}]", frames) for filt, frames in calib.flats_by_filter.items()]
        for label, frames in stacks:
            temps = [f.ccd_temp for f in frames if f.ccd_temp is not None]
            if temps and (max(temps) - min(temps)) > TEMP_SPREAD_WARN:
                result.warnings.append(
                    f"{label} stack: CCD-TEMP spread {max(temps) - min(temps):.1f}°C "
                    f"exceeds {TEMP_SPREAD_WARN}°C"
                )

    # Lights whose filter has no matching flats (but other calibration exists)
    for group in result.light_groups:
        if group.action is PlannedAction.CALIBRATE_THEN_UPLOAD:
            calib = result.calibration_for(group)
            if not calib.flats_for(group.filter_name):
                result.warnings.append(
                    f"{group.display_name}: no flats for this filter - "
                    "flat correction will be skipped"
                )

    # Dark exposure mismatches are informational (we scale by exposure)
    darks_exp = defaultdict(set)
    for calib in result.calibration_sets.values():
        for dark in calib.darks:
            if dark.exptime is not None:
                darks_exp["all"].add(dark.exptime)
    if len(darks_exp.get("all", set())) > 1:
        result.warnings.append(
            "darks with mixed exposure times found - master dark will be exposure-scaled"
        )

    unknown = result.frames_of(FrameType.UNKNOWN)
    if unknown:
        result.warnings.append(
            f"{len(unknown)} file(s) could not be classified - review and set their type manually"
        )
