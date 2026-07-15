"""Multi-extension FITS (raw LCO style) + compressed-name support."""
from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits

from bhtom_uploader.core.calibrator import Calibrator
from bhtom_uploader.core.models import Confidence, FrameType
from bhtom_uploader.core.scanner import (
    find_fits_files,
    is_fits_name,
    read_frame_info,
    scan_directory,
)


def make_mef(path, data, primary_cards: dict):
    """LCO-like layout: metadata-only primary + compressed image extension."""
    primary = fits.PrimaryHDU()
    for key, value in primary_cards.items():
        primary.header[key] = value
    comp = fits.CompImageHDU(np.asarray(data, dtype=np.float32), name="SCI")
    fits.HDUList([primary, comp]).writeto(path, overwrite=True)
    return path


LCO_LIGHT_CARDS = {
    "OBSTYPE": "EXPOSE",
    "OBJECT": "Gaia24amo",
    "EXPTIME": 200.0,
    "FILTER": "ip",
    "RA": 249.14892,
    "DEC": -53.74992,
    "DATE-OBS": "2025-07-14T20:00:00",
}


def test_is_fits_name_variants():
    assert is_fits_name("a.fits") and is_fits_name("A.FITS")
    assert is_fits_name("a.fit") and is_fits_name("a.fts")
    assert is_fits_name("cpt1m013-fa01-0171-e00.fits.fz")
    assert is_fits_name("a.fits.gz")
    assert not is_fits_name("a.txt")
    assert not is_fits_name("a.fz")  # bare .fz without a FITS stem


def test_mef_light_classified_from_primary_header(tmp_path):
    path = make_mef(tmp_path / "e00.fits", np.full((32, 32), 500.0), LCO_LIGHT_CARDS)
    info = read_frame_info(path)
    assert info.frame_type is FrameType.LIGHT
    assert info.confidence is Confidence.HIGH  # OBSTYPE=EXPOSE is explicit
    assert info.shape == (32, 32)              # from the image extension
    assert info.object_name == "Gaia24amo"
    assert info.exptime == pytest.approx(200.0)
    assert info.ra == pytest.approx(249.14892)
    assert info.dec == pytest.approx(-53.74992)


def test_fz_named_files_discovered_and_classified(tmp_path):
    path = make_mef(tmp_path / "raw.fits.fz", np.zeros((8, 8)), {"OBSTYPE": "BIAS"})
    assert path in find_fits_files(tmp_path)
    assert read_frame_info(path).frame_type is FrameType.BIAS


def test_mef_calibration_end_to_end(tmp_path):
    """MEF bias set + MEF light: signal recovered, provenance written."""
    rng = np.random.default_rng(5)
    for i in range(3):
        make_mef(
            tmp_path / f"bias_{i}.fits.fz",
            100.0 + rng.normal(0.0, 1.0, (32, 32)),
            {"OBSTYPE": "BIAS", "EXPTIME": 0.0},
        )
    make_mef(
        tmp_path / "sci.fits.fz",
        600.0 + rng.normal(0.0, 1.0, (32, 32)),  # bias 100 + signal 500
        LCO_LIGHT_CARDS,
    )
    scan = scan_directory(tmp_path)
    assert len(scan.light_groups) == 1
    group = scan.light_groups[0]
    calibrator = Calibrator(log=lambda m: None)
    results = calibrator.calibrate_group(group, scan.calibration_for(group), tmp_path / "out")
    out_path = results[0][1]
    with fits.open(out_path) as hdul:
        assert float(np.mean(hdul[0].data)) == pytest.approx(500.0, abs=2.0)
        assert hdul[0].header["CALSTAT"] == "B"
