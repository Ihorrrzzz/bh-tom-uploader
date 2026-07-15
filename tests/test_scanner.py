"""Scanner: classification decision table, calibrated-detection, grouping, planning."""
from __future__ import annotations

import numpy as np
import pytest

from bhtom_uploader.core.models import (
    CalibrationState,
    Confidence,
    FrameType,
    PlannedAction,
)
from bhtom_uploader.core.scanner import read_frame_info, scan_directory

from fixtures import (
    BASE_HEADER,
    make_bias,
    make_flat,
    make_light,
    make_night,
    write_fits,
    SHAPE,
)


@pytest.fixture
def rng():
    return np.random.default_rng(7)


# ---------------------------------------------------------------------------
# frame-type classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "imagetyp,expected",
    [
        ("Bias Frame", FrameType.BIAS),
        ("ZERO", FrameType.BIAS),
        ("Dark Frame", FrameType.DARK),
        ("Dark Flat", FrameType.DARK),  # dark-for-flats counts as dark
        ("Flat Field", FrameType.FLAT),
        ("FLAT", FrameType.FLAT),
        ("Light Frame", FrameType.LIGHT),
        ("OBJECT", FrameType.LIGHT),
        ("science", FrameType.LIGHT),
    ],
)
def test_imagetyp_classification(tmp_path, imagetyp, expected):
    path = write_fits(tmp_path / "frame.fits", np.zeros(SHAPE), {"IMAGETYP": imagetyp})
    info = read_frame_info(path)
    assert info.frame_type is expected
    assert info.confidence is Confidence.HIGH


def test_filename_fallback_classification(tmp_path):
    path = write_fits(tmp_path / "flat_V_001.fits", np.zeros(SHAPE), {})
    info = read_frame_info(path)
    assert info.frame_type is FrameType.FLAT
    assert info.confidence is Confidence.LOW


def test_object_keyword_fallback(tmp_path):
    header = {"OBJECT": "M31", "EXPTIME": 60.0}
    path = write_fits(tmp_path / "m31_0001.fits", np.zeros(SHAPE), header)
    info = read_frame_info(path)
    assert info.frame_type is FrameType.LIGHT
    assert info.confidence is Confidence.LOW


def test_unclassifiable_is_unknown(tmp_path):
    path = write_fits(tmp_path / "img0001.fits", np.zeros(SHAPE), {})
    info = read_frame_info(path)
    assert info.frame_type is FrameType.UNKNOWN


def test_unreadable_file_records_error(tmp_path):
    bad = tmp_path / "broken.fits"
    bad.write_bytes(b"this is not a FITS file at all")
    info = read_frame_info(bad)
    assert info.error is not None


# ---------------------------------------------------------------------------
# calibrated-vs-raw detection for lights
# ---------------------------------------------------------------------------

def _light_header(**extra):
    return {"IMAGETYP": "Light Frame", "OBJECT": "X", "EXPTIME": 10.0, **extra}


def test_calstat_marks_calibrated(tmp_path):
    path = write_fits(tmp_path / "a.fits", np.zeros(SHAPE), _light_header(CALSTAT="BDF"))
    info = read_frame_info(path)
    assert info.calibration_state is CalibrationState.CALIBRATED
    assert "CALSTAT" in info.calibration_evidence


def test_history_marker_marks_calibrated(tmp_path):
    header = _light_header(HISTORY="Calibrated: bias subtracted, flat fielded")
    path = write_fits(tmp_path / "b.fits", np.zeros(SHAPE), header)
    info = read_frame_info(path)
    assert info.calibration_state is CalibrationState.CALIBRATED


def test_calibfits_suffix_marks_calibrated(tmp_path):
    path = write_fits(tmp_path / "ngc7000-bdf.fits", np.zeros(SHAPE), _light_header())
    info = read_frame_info(path)
    assert info.calibration_state is CalibrationState.CALIBRATED


def test_calibrated_prefix_marks_calibrated(tmp_path):
    path = write_fits(tmp_path / "calibrated_light_001.fits", np.zeros(SHAPE), _light_header())
    info = read_frame_info(path)
    assert info.calibration_state is CalibrationState.CALIBRATED


def test_plain_light_is_raw(tmp_path):
    path = write_fits(tmp_path / "light_0001.fits", np.zeros(SHAPE), _light_header())
    info = read_frame_info(path)
    assert info.calibration_state is CalibrationState.RAW


# ---------------------------------------------------------------------------
# header metadata extraction
# ---------------------------------------------------------------------------

def test_metadata_extraction(tmp_path, rng):
    path = make_light(tmp_path / "l.fits", rng)
    info = read_frame_info(path)
    assert info.object_name == "TESTOBJ"
    assert info.filter_name == "V"
    assert info.exptime == pytest.approx(10.0)
    assert info.binning == (1, 1)
    assert info.ccd_temp == pytest.approx(-10.0)
    assert info.ra == pytest.approx(123.456)
    assert info.dec == pytest.approx(-45.678)
    assert info.shape == SHAPE


def test_sexagesimal_ra_dec(tmp_path):
    header = _light_header(OBJCTRA="12 30 00", OBJCTDEC="-45 30 00")
    del header["EXPTIME"]
    header["EXPTIME"] = 10.0
    path = write_fits(tmp_path / "s.fits", np.zeros(SHAPE), header)
    info = read_frame_info(path)
    assert info.ra == pytest.approx(187.5)       # 12h30m -> 187.5 deg
    assert info.dec == pytest.approx(-45.5)


# ---------------------------------------------------------------------------
# scan + plan scenarios (the product's three core flows)
# ---------------------------------------------------------------------------

def test_scenario_calibrate_then_upload(tmp_path):
    """(a) raw lights + calibration set -> calibrate then upload."""
    make_night(tmp_path)
    scan = scan_directory(tmp_path)
    assert len(scan.light_groups) == 1
    group = scan.light_groups[0]
    assert group.action is PlannedAction.CALIBRATE_THEN_UPLOAD
    assert not scan.needs_confirmation
    calib = scan.calibration_for(group)
    assert calib.has_bias and calib.has_dark and calib.flats_for("V")


def test_scenario_direct_upload(tmp_path, rng):
    """(b) already-calibrated lights only -> upload directly."""
    for i in range(3):
        make_light(tmp_path / f"calibrated_light_{i}.fits", rng, CALSTAT="BDF")
    scan = scan_directory(tmp_path)
    assert len(scan.light_groups) == 1
    assert scan.light_groups[0].action is PlannedAction.UPLOAD_DIRECT
    assert not scan.needs_confirmation


def test_scenario_raw_needs_confirmation(tmp_path, rng):
    """(c) raw lights, no calibration frames -> explicit user confirmation."""
    for i in range(2):
        make_light(tmp_path / f"light_{i}.fits", rng)
    scan = scan_directory(tmp_path)
    assert scan.light_groups[0].action is PlannedAction.UPLOAD_RAW_CONFIRM
    assert scan.needs_confirmation


def test_groups_split_by_filter(tmp_path, rng):
    make_light(tmp_path / "v1.fits", rng, filter_name="V")
    make_light(tmp_path / "r1.fits", rng, filter_name="R")
    scan = scan_directory(tmp_path)
    assert len(scan.light_groups) == 2
    assert {g.filter_name for g in scan.light_groups} == {"V", "R"}


def test_flats_grouped_by_filter(tmp_path, rng):
    make_flat(tmp_path / "fv.fits", rng, filter_name="V")
    make_flat(tmp_path / "fr.fits", rng, filter_name="R")
    make_bias(tmp_path / "b.fits", rng)
    scan = scan_directory(tmp_path)
    calib = next(iter(scan.calibration_sets.values()))
    assert set(calib.flats_by_filter) == {"V", "R"}


def test_own_output_folder_excluded(tmp_path, rng):
    make_light(tmp_path / "light_1.fits", rng)
    # our own previous output must not be re-scanned
    make_light(tmp_path / "Calibrated files" / "calibrated_light_1.fits", rng, CALSTAT="BDF")
    scan = scan_directory(tmp_path)
    assert len(scan.frames) == 1


def test_missing_flat_filter_warns(tmp_path, rng):
    make_light(tmp_path / "l.fits", rng, filter_name="R")
    make_bias(tmp_path / "b.fits", rng)
    make_flat(tmp_path / "f.fits", rng, filter_name="V")  # wrong filter
    scan = scan_directory(tmp_path)
    assert scan.light_groups[0].action is PlannedAction.CALIBRATE_THEN_UPLOAD
    assert any("no flats for this filter" in w for w in scan.warnings)


def test_summary_line(tmp_path):
    make_night(tmp_path, n_bias=3, n_dark=3, n_flat=3, n_light=2)
    scan = scan_directory(tmp_path)
    summary = scan.summary()
    assert "2 light" in summary and "3 bias" in summary
