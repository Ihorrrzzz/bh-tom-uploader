"""Saturated-pixel protection: census, flagging, adjusted SATURATE keyword."""
from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits

from bhtom_uploader.core.calibrator import Calibrator
from bhtom_uploader.core.scanner import read_frame_info, scan_directory

from fixtures import BIAS_LEVEL, make_bias, make_light, make_night


@pytest.fixture
def rng():
    return np.random.default_rng(21)


def test_scanner_parses_saturate_keyword(tmp_path, rng):
    path = make_light(tmp_path / "l.fits", rng, SATURATE=47500.0)
    assert read_frame_info(path).saturate == pytest.approx(47500.0)


def _calibrated_header(tmp_path, saturate_kw=None, hot_pixels=0, override=None):
    make_night(tmp_path, n_light=0)
    extra = {} if saturate_kw is None else {"SATURATE": saturate_kw}
    rng = np.random.default_rng(3)
    light = make_light(tmp_path / "light_x.fits", rng, **extra)
    if hot_pixels:
        with fits.open(light, mode="update") as hdul:
            flat_view = hdul[0].data.reshape(-1)
            flat_view[:hot_pixels] = 60000.0  # at/above the ceiling
    scan = scan_directory(tmp_path)
    group = scan.light_groups[0]
    calibrator = Calibrator(saturation_adu=override, log=lambda m: None)
    results = calibrator.calibrate_group(group, scan.calibration_for(group), tmp_path / "out")
    frame_result = next(r for r in results if r[0].name == "light_x.fits")
    with fits.open(frame_result[1]) as hdul:
        return hdul[0].header, frame_result[2]


def test_saturated_pixels_flagged_and_level_adjusted(tmp_path):
    header, note = _calibrated_header(tmp_path, saturate_kw=60000.0, hot_pixels=5)
    assert header["NSATPIX"] == 5
    assert header["SATORIG"] == 60000.0
    # ceiling drops by the subtracted bias pedestal (and scaled dark)
    assert header["SATURATE"] < 60000.0 - BIAS_LEVEL + 5.0
    assert "5 saturated px" in note


def test_clean_frame_reports_zero(tmp_path):
    header, note = _calibrated_header(tmp_path, saturate_kw=60000.0, hot_pixels=0)
    assert header["NSATPIX"] == 0
    assert note == "calibrated"


def test_no_saturate_info_means_no_flags(tmp_path):
    header, note = _calibrated_header(tmp_path, saturate_kw=None, hot_pixels=3)
    assert "NSATPIX" not in header
    assert note == "calibrated"


def test_manual_override_beats_header(tmp_path):
    # header claims 60000 but the user knows the true ceiling is 500 ADU:
    # the whole synthetic frame (bias+signal ~600) is then saturated
    header, note = _calibrated_header(tmp_path, saturate_kw=60000.0, hot_pixels=0, override=500.0)
    assert header["SATORIG"] == 500.0
    assert header["NSATPIX"] == 32 * 32
    assert "saturated px" in note
