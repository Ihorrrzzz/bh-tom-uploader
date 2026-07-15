"""Pipeline: end-to-end calibrate->upload against a synthetic night + mocked HTTP."""
from __future__ import annotations

import numpy as np
import pytest
import responses

from bhtom_uploader.core.bhtom import BHTOMClient
from bhtom_uploader.core.models import UploadStatus
from bhtom_uploader.core.pipeline import Pipeline, RunOptions
from bhtom_uploader.core.scanner import scan_directory

from fixtures import make_light, make_night

BASE = "https://bhtom.test"
UPLOAD = "https://upload.test"


@pytest.fixture(scope="session", autouse=True)
def qcore_app():
    """QObject signals want a QCoreApplication around."""
    from PySide6.QtCore import QCoreApplication

    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def client():
    c = BHTOMClient(base_url=BASE, upload_url=UPLOAD)
    c.token = "test-token"
    return c


def run_pipeline(scan, options, client):
    pipeline = Pipeline(scan, options, client)
    reports = []
    fatals = []
    pipeline.finished.connect(reports.append)
    pipeline.failed.connect(fatals.append)
    pipeline.run()
    return reports[0] if reports else None, fatals


@responses.activate
def test_calibrate_then_upload_flow(tmp_path, client):
    responses.post(
        f"{UPLOAD}/upload/",
        json={"Success": [{"file name:": "x.fits", "id": "77", "message": "Received plain FITS file."}]},
    )
    make_night(tmp_path)  # 2 raw lights + full calibration set
    scan = scan_directory(tmp_path)
    report, fatals = run_pipeline(scan, RunOptions(target="T1", observatory="OB"), client)

    assert not fatals
    assert report.n_success == 2 and report.n_failed == 0
    # calibrated outputs (not the raw originals) were uploaded
    for item in report.items:
        assert item.upload_path.name.startswith("calibrated_")
        assert item.dataproduct_ids == [77]
    assert (tmp_path / "Calibrated files").exists()
    # every upload request carried the multipart fields
    assert len(responses.calls) == 2


@responses.activate
def test_direct_upload_of_calibrated_lights(tmp_path, client):
    responses.post(f"{UPLOAD}/upload/", json={"Success": [{"id": 5}]})
    rng = np.random.default_rng(3)
    for i in range(2):
        make_light(tmp_path / f"sci_{i}.fits", rng, CALSTAT="BDF")
    scan = scan_directory(tmp_path)
    report, fatals = run_pipeline(scan, RunOptions(target="T2", observatory="OB"), client)

    assert not fatals and report.n_success == 2
    for item in report.items:
        assert item.upload_path == item.source  # originals, untouched
    assert not (tmp_path / "Calibrated files").exists()


def test_raw_without_confirmation_is_skipped(tmp_path, client):
    rng = np.random.default_rng(4)
    make_light(tmp_path / "raw1.fits", rng)
    scan = scan_directory(tmp_path)
    report, fatals = run_pipeline(
        scan, RunOptions(target="T3", observatory="OB", allow_raw=False), client
    )
    assert not fatals
    assert report.n_skipped == 1 and report.n_success == 0  # and no HTTP call happened


@responses.activate
def test_raw_with_confirmation_uploads(tmp_path, client):
    responses.post(f"{UPLOAD}/upload/", json={"Success": [{"id": 9}]})
    rng = np.random.default_rng(5)
    make_light(tmp_path / "raw1.fits", rng)
    scan = scan_directory(tmp_path)
    report, _ = run_pipeline(
        scan, RunOptions(target="T4", observatory="OB", allow_raw=True), client
    )
    assert report.n_success == 1


@responses.activate
def test_upload_failure_marks_item_and_continues(tmp_path, client):
    responses.post(f"{UPLOAD}/upload/", status=502)
    responses.post(f"{UPLOAD}/upload/", json={"Success": [{"id": 6}]})
    rng = np.random.default_rng(6)
    make_light(tmp_path / "a1.fits", rng, CALSTAT="BDF")
    make_light(tmp_path / "a2.fits", rng, CALSTAT="BDF")
    scan = scan_directory(tmp_path)
    report, fatals = run_pipeline(scan, RunOptions(target="T5", observatory="OB"), client)

    assert not fatals
    assert report.n_failed == 1 and report.n_success == 1
    statuses = sorted(i.status.value for i in report.items)
    assert statuses == ["failed", "uploaded"]


@responses.activate
def test_dry_run_flag_sent(tmp_path, client):
    seen = {}

    def check(request):
        body = request.body.read() if hasattr(request.body, "read") else request.body
        seen["dry_run_true"] = b'name="dry_run"' in body and b"True" in body
        return (200, {}, '{"Success": [{"id": 1}]}')

    responses.add_callback(responses.POST, f"{UPLOAD}/upload/", callback=check)
    rng = np.random.default_rng(8)
    make_light(tmp_path / "c.fits", rng, CALSTAT="BDF")
    scan = scan_directory(tmp_path)
    run_pipeline(scan, RunOptions(target="T6", observatory="OB", dry_run=True), client)
    assert seen["dry_run_true"]
