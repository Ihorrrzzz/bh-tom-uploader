"""CCD calibration engine built on ccdproc.

Architecture follows the author's calib-fits pipeline (step order, screening,
master library, log callback) with the scientifically corrected recipe:

* masters combined with **sigma-clipped average** (proper masked-array handling)
  and a memory limit for large sensors;
* darks are **bias-subtracted first**, then normalized to a 1-second dark-rate
  master, so exposure scaling never scales the bias pedestal;
* flats are **bias- and dark-corrected before combining**, inverse-median scaled,
  grouped per filter;
* every output carries provenance: ``CALSTAT`` + ``HISTORY BHTOM-UPLOADER ...``
  (read back by :mod:`bhtom_uploader.core.scanner` to recognize calibrated frames).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import ccdproc
from astropy import units as u
from astropy.nddata import CCDData
from astropy.stats import mad_std

from .. import __version__
from .models import CalibrationSet, CalibrationState, FrameInfo, LightGroup

DEFAULT_MEM_LIMIT = 2_000_000_000  # bytes; chunked combining above this
MIN_STACK_WARN = 3                 # fewer frames than this in a stack -> warn

LogFn = Callable[[str], None]


class CalibrationError(Exception):
    """A calibration step could not proceed (bad inputs, shape mismatch, ...)."""


def _noop_log(_msg: str) -> None:
    pass


def _read_ccd(path: Path) -> CCDData:
    """Read a FITS file as CCDData, defaulting to ADU when BUNIT is absent."""
    try:
        return CCDData.read(path)
    except ValueError:
        return CCDData.read(path, unit="adu")


def _add_history(meta, text: str) -> None:
    if hasattr(meta, "add_history"):
        meta.add_history(text)
    else:  # plain dict-like fallback
        meta.setdefault("HISTORY", [])
        meta["HISTORY"].append(text)


def _provenance_line(steps: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"BHTOM-UPLOADER v{__version__} calibrated ({steps}) {stamp}"


def _check_shapes(frames: list[FrameInfo], label: str) -> None:
    shapes = {f.shape for f in frames}
    if len(shapes) > 1:
        raise CalibrationError(
            f"{label} stack mixes frame shapes {sorted(shapes)} - "
            "these cannot be combined; check binning/subframe settings"
        )


def _combine(ccds: list[CCDData], mem_limit: float) -> CCDData:
    """Sigma-clipped average combine (the standard ccdproc reduction recipe)."""
    return ccdproc.combine(
        ccds,
        method="average",
        sigma_clip=True,
        sigma_clip_low_thresh=5,
        sigma_clip_high_thresh=5,
        sigma_clip_func=np.ma.median,
        sigma_clip_dev_func=mad_std,
        mem_limit=mem_limit,
        unit="adu",
    )


class Calibrator:
    """Builds master frames and calibrates light frames for one scan.

    Masters are cached per stack configuration and written to
    ``<out_dir>/masters`` for transparency and reuse.
    """

    def __init__(
        self,
        mem_limit: float = DEFAULT_MEM_LIMIT,
        flat_min_adu: Optional[float] = None,
        flat_max_adu: Optional[float] = None,
        cosmic_ray: bool = False,
        log: Optional[LogFn] = None,
    ) -> None:
        self.mem_limit = mem_limit
        self.flat_min_adu = flat_min_adu
        self.flat_max_adu = flat_max_adu
        self.cosmic_ray = cosmic_ray
        self.log: LogFn = log or _noop_log
        self._master_bias: dict[tuple, Optional[CCDData]] = {}
        self._master_dark: dict[tuple, Optional[CCDData]] = {}
        self._master_flat: dict[tuple, Optional[CCDData]] = {}

    # ------------------------------------------------------------------
    # Master frames
    # ------------------------------------------------------------------

    def master_bias(self, calib: CalibrationSet, key: tuple, masters_dir: Path) -> Optional[CCDData]:
        if key not in self._master_bias:
            self._master_bias[key] = self._build_master_bias(calib, masters_dir)
        return self._master_bias[key]

    def _build_master_bias(self, calib: CalibrationSet, masters_dir: Path) -> Optional[CCDData]:
        if not calib.biases:
            return None
        _check_shapes(calib.biases, "bias")
        if len(calib.biases) < MIN_STACK_WARN:
            self.log(f"only {len(calib.biases)} bias frame(s) - master bias will be noisy")
        self.log(f"combining {len(calib.biases)} bias frames (sigma-clipped average)")
        ccds = [_read_ccd(f.path) for f in calib.biases]
        master = _combine(ccds, self.mem_limit)
        master.meta["IMAGETYP"] = "Master Bias"
        master.meta["NCOMBINE"] = len(ccds)
        _add_history(master.meta, _provenance_line("master bias"))
        self._write_master(master, masters_dir / "masterbias.fits")
        return master

    def master_dark(
        self, calib: CalibrationSet, key: tuple, masters_dir: Path, bias: Optional[CCDData]
    ) -> Optional[CCDData]:
        if key not in self._master_dark:
            self._master_dark[key] = self._build_master_dark(calib, masters_dir, bias)
        return self._master_dark[key]

    def _build_master_dark(
        self, calib: CalibrationSet, masters_dir: Path, bias: Optional[CCDData]
    ) -> Optional[CCDData]:
        """Master dark normalized to a 1-second rate, from bias-subtracted darks."""
        usable = [f for f in calib.darks if (f.exptime or 0) > 0]
        for skipped in (f for f in calib.darks if (f.exptime or 0) <= 0):
            self.log(f"skipping dark {skipped.name}: no positive EXPTIME")
        if not usable:
            return None
        _check_shapes(usable, "dark")
        if len(usable) < MIN_STACK_WARN:
            self.log(f"only {len(usable)} dark frame(s) - master dark will be noisy")
        exposures = sorted({f.exptime for f in usable})
        self.log(
            f"combining {len(usable)} dark frames (exposures {exposures}s, "
            "bias-subtracted, scaled to 1s rate)"
        )
        ccds: list[CCDData] = []
        for frame in usable:
            ccd = _read_ccd(frame.path)
            if bias is not None:
                ccd = ccdproc.subtract_bias(ccd, bias)
            ccd.data = ccd.data / float(frame.exptime)  # per-second dark current
            ccds.append(ccd)
        master = _combine(ccds, self.mem_limit)
        master.meta["IMAGETYP"] = "Master Dark"
        master.meta["NCOMBINE"] = len(ccds)
        master.meta["EXPTIME"] = 1.0  # rate frame: 1-second equivalent
        master.meta["BIASSUB"] = bias is not None
        _add_history(master.meta, _provenance_line("master dark, 1s rate"))
        self._write_master(master, masters_dir / "masterdark.fits")
        return master

    def master_flat(
        self,
        calib: CalibrationSet,
        key: tuple,
        filter_name: Optional[str],
        masters_dir: Path,
        bias: Optional[CCDData],
        dark: Optional[CCDData],
    ) -> Optional[CCDData]:
        cache_key = (key, filter_name or "")
        if cache_key not in self._master_flat:
            self._master_flat[cache_key] = self._build_master_flat(
                calib, filter_name, masters_dir, bias, dark
            )
        return self._master_flat[cache_key]

    def _build_master_flat(
        self,
        calib: CalibrationSet,
        filter_name: Optional[str],
        masters_dir: Path,
        bias: Optional[CCDData],
        dark: Optional[CCDData],
    ) -> Optional[CCDData]:
        flats = calib.flats_for(filter_name)
        if not flats:
            return None
        _check_shapes(flats, f"flat[{filter_name or 'no filter'}]")
        ccds: list[CCDData] = []
        for frame in flats:
            ccd = _read_ccd(frame.path)
            mean_adu = float(np.mean(ccd.data))
            if self.flat_min_adu is not None and mean_adu < self.flat_min_adu:
                self.log(f"rejecting flat {frame.name}: mean {mean_adu:.0f} ADU below minimum")
                continue
            if self.flat_max_adu is not None and mean_adu > self.flat_max_adu:
                self.log(f"rejecting flat {frame.name}: mean {mean_adu:.0f} ADU above maximum (saturated?)")
                continue
            if bias is not None:
                ccd = ccdproc.subtract_bias(ccd, bias)
            if dark is not None and (frame.exptime or 0) > 0:
                ccd = ccdproc.subtract_dark(
                    ccd, dark, exposure_time="EXPTIME", exposure_unit=u.s, scale=True
                )
            ccds.append(ccd)
        if not ccds:
            self.log(f"no usable flats remain for filter '{filter_name or ''}' after screening")
            return None
        if len(ccds) < MIN_STACK_WARN:
            self.log(f"only {len(ccds)} flat frame(s) for '{filter_name or ''}' - master flat will be noisy")
        self.log(
            f"combining {len(ccds)} flat frames for filter '{filter_name or ''}' "
            "(bias/dark-corrected, inverse-median scaled)"
        )
        master = ccdproc.combine(
            ccds,
            method="average",
            scale=lambda arr: 1.0 / np.ma.median(arr),
            sigma_clip=True,
            sigma_clip_low_thresh=5,
            sigma_clip_high_thresh=5,
            sigma_clip_func=np.ma.median,
            sigma_clip_dev_func=mad_std,
            mem_limit=self.mem_limit,
            unit="adu",
        )
        master.meta["IMAGETYP"] = "Master Flat"
        master.meta["FILTER"] = filter_name or ""
        master.meta["NCOMBINE"] = len(ccds)
        _add_history(master.meta, _provenance_line(f"master flat [{filter_name or ''}]"))
        safe_filter = "".join(c if c.isalnum() or c in "-_" else "_" for c in (filter_name or "none"))
        self._write_master(master, masters_dir / f"masterflat_{safe_filter}.fits")
        return master

    def _write_master(self, master: CCDData, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            master.write(path, overwrite=True)
            self.log(f"master written: {path.name}")
        except Exception as exc:  # non-fatal: master still usable in memory
            self.log(f"could not write {path.name}: {exc}")

    # ------------------------------------------------------------------
    # Light frame calibration
    # ------------------------------------------------------------------

    def calibrate_group(
        self, group: LightGroup, calib: CalibrationSet, out_dir: Path
    ) -> list[tuple[FrameInfo, Path, str]]:
        """Calibrate every raw light in the group.

        Returns ``(frame, path_to_upload, note)`` per frame - already-calibrated
        frames pass through with their original path.
        """
        out_dir = Path(out_dir)
        masters_dir = out_dir / "masters"
        key = group.stack_key

        bias = self.master_bias(calib, key, masters_dir)
        dark = self.master_dark(calib, key, masters_dir, bias)
        flat = self.master_flat(calib, key, group.filter_name, masters_dir, bias, dark)
        if bias is None and dark is None and flat is None:
            raise CalibrationError(
                f"{group.display_name}: no usable calibration frames "
                "(bias/dark/flat all unavailable)"
            )

        results: list[tuple[FrameInfo, Path, str]] = []
        for frame in group.frames:
            if frame.calibration_state is CalibrationState.CALIBRATED:
                results.append((frame, frame.path, f"already calibrated ({frame.calibration_evidence})"))
                continue
            out_path = self.calibrate_light(frame, bias, dark, flat, out_dir)
            results.append((frame, out_path, "calibrated"))
        return results

    def calibrate_light(
        self,
        frame: FrameInfo,
        bias: Optional[CCDData],
        dark: Optional[CCDData],
        flat: Optional[CCDData],
        out_dir: Path,
    ) -> Path:
        """Apply bias/dark/flat (whatever is available) to one light frame and save it."""
        ccd = _read_ccd(frame.path)
        if frame.shape and bias is not None and ccd.data.shape != bias.data.shape:
            raise CalibrationError(
                f"{frame.name}: shape {ccd.data.shape} does not match master bias "
                f"{bias.data.shape} - mixed binning/subframe?"
            )
        steps = ""
        if bias is not None:
            ccd = ccdproc.subtract_bias(ccd, bias)
            steps += "B"
        if dark is not None:
            if (frame.exptime or 0) > 0:
                ccd = ccdproc.subtract_dark(
                    ccd, dark, exposure_time="EXPTIME", exposure_unit=u.s, scale=True
                )
                steps += "D"
            else:
                self.log(f"{frame.name}: no EXPTIME - dark subtraction skipped")
        if flat is not None:
            ccd = ccdproc.flat_correct(ccd, flat, min_value=0.1)
            steps += "F"
        if self.cosmic_ray:
            self.log(f"{frame.name}: removing cosmic rays (L.A.Cosmic)")
            ccd = ccdproc.cosmicray_lacosmic(ccd, sigclip=4.5)

        # sanitize + compact
        ccd.data = np.nan_to_num(ccd.data, nan=0.0, posinf=0.0, neginf=0.0).astype("float32")

        # provenance (scanner reads this back to recognize calibrated frames)
        ccd.meta["CALSTAT"] = steps
        _add_history(ccd.meta, _provenance_line(",".join(steps)))

        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"calibrated_{frame.path.name}"
        ccd.write(out_path, overwrite=True)
        self.log(f"{frame.name}: calibrated ({steps or 'no steps applied'}) -> {out_path.name}")
        return out_path
