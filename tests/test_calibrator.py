"""Calibrator: known pixel math in, science signal out."""
from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits

from bhtom_uploader.core.calibrator import Calibrator, CalibrationError
from bhtom_uploader.core.models import CalibrationState, PlannedAction
from bhtom_uploader.core.scanner import read_frame_info, scan_directory

from fixtures import (
    LIGHT_SIGNAL,
    SHAPE,
    make_bias,
    make_light,
    make_night,
    write_fits,
)


@pytest.fixture
def rng():
    return np.random.default_rng(11)


def _calibrate_night(tmp_path):
    make_night(tmp_path)
    scan = scan_directory(tmp_path)
    group = scan.light_groups[0]
    assert group.action is PlannedAction.CALIBRATE_THEN_UPLOAD
    calibrator = Calibrator(log=lambda msg: None)
    out_dir = tmp_path / "Calibrated files"
    results = calibrator.calibrate_group(group, scan.calibration_for(group), out_dir)
    return scan, results, out_dir


def test_full_calibration_recovers_signal(tmp_path):
    """bias + exposure-scaled dark + flat all removed -> flat field of LIGHT_SIGNAL.

    The synthetic dark exposure (20 s) deliberately differs from the light
    exposure (10 s), so this also proves correct exposure scaling of the
    bias-subtracted master dark.
    """
    _, results, _ = _calibrate_night(tmp_path)
    assert len(results) == 2
    for _frame, out_path, note in results:
        assert note == "calibrated"
        with fits.open(out_path) as hdul:
            data = hdul[0].data
        assert data.shape == SHAPE
        # mean recovers the source signal; gradient (vignetting) removed
        assert float(np.mean(data)) == pytest.approx(LIGHT_SIGNAL, abs=3.0)
        assert float(np.std(data)) < 5.0  # flat gradient (~±20%) would give std ~58


def test_provenance_written_and_recognized(tmp_path):
    """Outputs carry CALSTAT + HISTORY, and the scanner recognizes them as calibrated."""
    _, results, _ = _calibrate_night(tmp_path)
    out_path = results[0][1]
    with fits.open(out_path) as hdul:
        header = hdul[0].header
    assert header["CALSTAT"] == "BDF"
    history = " ".join(str(h) for h in header["HISTORY"])
    assert "BHTOM-UPLOADER" in history

    # round-trip: a rescan must classify the output as an already-calibrated light
    info = read_frame_info(out_path)
    assert info.calibration_state is CalibrationState.CALIBRATED


def test_masters_written(tmp_path):
    _, _, out_dir = _calibrate_night(tmp_path)
    masters = out_dir / "masters"
    assert (masters / "masterbias.fits").exists()
    assert (masters / "masterdark.fits").exists()
    assert (masters / "masterflat_V.fits").exists()
    # master dark is a 1-second rate frame
    with fits.open(masters / "masterdark.fits") as hdul:
        assert hdul[0].header["EXPTIME"] == 1.0


def test_sigma_clip_rejects_hot_pixel(tmp_path, rng):
    """A 5000-ADU hot pixel in one of six bias frames must not survive combining."""
    from bhtom_uploader.core.models import CalibrationSet

    frames = []
    for i in range(6):
        path = make_bias(tmp_path / f"bias_{i}.fits", rng)
        if i == 0:  # inject outlier into the first frame
            with fits.open(path, mode="update") as hdul:
                hdul[0].data[5, 5] = 5000.0
        frames.append(read_frame_info(path))

    calib = CalibrationSet(biases=frames)
    calibrator = Calibrator(log=lambda msg: None)
    master = calibrator.master_bias(calib, frames[0].stack_key, tmp_path / "masters")
    # naive mean would be ~916 ADU at [5,5]; sigma-clipped must stay ~100
    assert float(master.data[5, 5]) == pytest.approx(100.0, abs=10.0)


def test_already_calibrated_passes_through(tmp_path, rng):
    make_night(tmp_path, n_light=1)
    done = make_light(tmp_path / "done.fits", rng, CALSTAT="BDF")
    scan = scan_directory(tmp_path)
    group = scan.light_groups[0]
    assert group.n_calibrated == 1 and group.n_raw == 1
    calibrator = Calibrator(log=lambda msg: None)
    results = calibrator.calibrate_group(group, scan.calibration_for(group), tmp_path / "out")
    by_source = {frame.path.name: (path, note) for frame, path, note in results}
    passthrough_path, passthrough_note = by_source["done.fits"]
    assert passthrough_path == done  # untouched original
    assert "already calibrated" in passthrough_note


def test_flat_screening_rejects_saturated(tmp_path, rng):
    make_night(tmp_path)
    calibrator = Calibrator(flat_max_adu=10000.0, log=lambda msg: None)  # flats mean ~20100
    scan = scan_directory(tmp_path)
    group = scan.light_groups[0]
    results = calibrator.calibrate_group(group, scan.calibration_for(group), tmp_path / "out")
    # all flats screened out -> flat step skipped -> CALSTAT 'BD'
    with fits.open(results[0][1]) as hdul:
        assert hdul[0].header["CALSTAT"] == "BD"


def test_shape_mismatch_raises(tmp_path, rng):
    from bhtom_uploader.core.models import CalibrationSet

    p1 = make_bias(tmp_path / "b1.fits", rng)
    p2 = write_fits(tmp_path / "b2.fits", np.zeros((16, 16)), {"IMAGETYP": "Bias Frame"})
    calib = CalibrationSet(biases=[read_frame_info(p1), read_frame_info(p2)])
    calibrator = Calibrator(log=lambda msg: None)
    with pytest.raises(CalibrationError, match="shape"):
        calibrator.master_bias(calib, (SHAPE, (1, 1)), tmp_path / "masters")


def test_no_calibration_frames_raises(tmp_path, rng):
    from bhtom_uploader.core.models import CalibrationSet, LightGroup

    light = read_frame_info(make_light(tmp_path / "l.fits", rng))
    group = LightGroup(object_name="X", filter_name="V", stack_key=light.stack_key, frames=[light])
    calibrator = Calibrator(log=lambda msg: None)
    with pytest.raises(CalibrationError, match="no usable calibration frames"):
        calibrator.calibrate_group(group, CalibrationSet(), tmp_path / "out")
