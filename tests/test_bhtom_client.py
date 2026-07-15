"""BHTOM API client: request shapes, response parsing, error taxonomy (mocked HTTP)."""
from __future__ import annotations

import numpy as np
import pytest
import responses

import bhtom_uploader.core.bhtom as bhtom_mod
from bhtom_uploader.core.bhtom import (
    AuthError,
    BHTOMClient,
    NetworkError,
    ServerError,
    TargetMissingError,
    ValidationError,
    _extract_ids,
)

BASE = "https://bhtom.test"
UPLOAD = "https://upload.test"


@pytest.fixture
def client():
    return BHTOMClient(base_url=BASE, upload_url=UPLOAD)


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(bhtom_mod, "RETRY_BACKOFF_S", 0.01)


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

@responses.activate
def test_login_success_sets_token(client):
    responses.post(f"{BASE}/api/token-auth/", json={"token": "abc123"})
    token = client.login("user", "pass")
    assert token == "abc123"
    assert client.session.headers["Authorization"] == "Token abc123"


@responses.activate
def test_login_bad_credentials(client):
    responses.post(f"{BASE}/api/token-auth/", json={"non_field_errors": ["bad"]}, status=400)
    with pytest.raises(AuthError, match="invalid username or password"):
        client.login("user", "wrong")


@responses.activate
def test_me_requires_valid_token(client):
    responses.get(f"{BASE}/common/api/users/me/", json={"username": "ihor"})
    client.token = "t"
    assert client.me()["username"] == "ihor"


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------

@responses.activate
def test_upload_sends_documented_multipart_fields(client, tmp_path):
    fits_file = tmp_path / "frame.fits"
    fits_file.write_bytes(b"SIMPLE  =                    T")

    def check_request(request):
        body = request.body.read() if hasattr(request.body, "read") else request.body
        text = body.decode("latin-1")
        for field in ("target", "filter", "data_product_type", "dry_run", "observatory"):
            assert f'name="{field}"' in text
        assert 'name="files"' in text
        assert "MyTarget" in text and "AZT-8_C4-16000" in text
        return (200, {}, '{"files": [{"id": 41}, {"id": 42}]}')

    responses.add_callback(responses.POST, f"{UPLOAD}/upload/", callback=check_request)
    ids, payload = client.upload_fits(
        fits_file, target="MyTarget", observatory="AZT-8_C4-16000", dry_run=True
    )
    assert ids == [41, 42]
    assert payload["files"][0]["id"] == 41


@pytest.mark.parametrize(
    "body,status",
    [
        ({"target": ["Target 'XYZ' does not exist in the bhtom."]}, 200),  # legacy shape
        ({"non_field_errors": ["Target 'XYZ' does not exist."]}, 400),     # shape verified live
    ],
)
@responses.activate
def test_upload_missing_target_raises_typed_error(client, tmp_path, body, status):
    fits_file = tmp_path / "f.fits"
    fits_file.write_bytes(b"x")
    responses.post(f"{UPLOAD}/upload/", json=body, status=status)
    with pytest.raises(TargetMissingError) as excinfo:
        client.upload_fits(fits_file, target="XYZ", observatory="OBS")
    assert excinfo.value.target == "XYZ"


@responses.activate
def test_upload_validation_error(client, tmp_path):
    fits_file = tmp_path / "f.fits"
    fits_file.write_bytes(b"x")
    responses.post(f"{UPLOAD}/upload/", json={"non_field_errors": ["bad observatory"]})
    with pytest.raises(ValidationError, match="bad observatory"):
        client.upload_fits(fits_file, target="T", observatory="nope")


# ---------------------------------------------------------------------------
# targets
# ---------------------------------------------------------------------------

@responses.activate
def test_target_exists_exact_match(client):
    responses.post(
        f"{BASE}/targets/getTargetList/",
        json={"results": [{"name": "Gaia22bpl"}, {"name": "Gaia22bpl-2"}]},
    )
    assert client.target_exists("gaia22bpl") is True


@responses.activate
def test_target_exists_no_match(client):
    responses.post(f"{BASE}/targets/getTargetList/", json={"results": []})
    assert client.target_exists("Nope123") is False


@responses.activate
def test_create_target_payload(client):
    def check(request):
        import json

        payload = json.loads(request.body)
        assert payload["name"] == "NewT" and payload["ra"] == 10.5 and payload["dec"] == -3.25
        assert payload["epoch"] == 2000.0 and payload["classification"] == "Unknown"
        return (201, {}, '{"name": "NewT"}')

    responses.add_callback(responses.POST, f"{BASE}/targets/createTarget/", callback=check)
    assert client.create_target("NewT", ra=10.5, dec=-3.25)["name"] == "NewT"


@responses.activate
def test_download_photometry_returns_text(client):
    body = "MJD;Magnitude;Error;Facility;Filter;Observer\n60000.5;15.2;0.03;AZT-8;GaiaSP/V;ihor"
    responses.post(f"{BASE}/targets/download-photometry/", body=body)
    assert client.download_photometry("T").startswith("MJD;")


# ---------------------------------------------------------------------------
# calibration results
# ---------------------------------------------------------------------------

@responses.activate
def test_get_calibration_results_payload(client):
    def check(request):
        import json

        payload = json.loads(request.body)
        assert payload["calibid"] == [41, 42] and payload["getPlot"] is False
        return (200, {}, '[{"id": 41, "status": "SUCCESS", "mag": 15.2, "mag_err": 0.05}]')

    responses.add_callback(
        responses.POST, f"{BASE}/calibration/get-calibration-res/", callback=check
    )
    records = client.get_calibration_results(calib_ids=[41, 42])
    assert records[0]["status"] == "SUCCESS"


def test_parse_verdict_success():
    verdict = BHTOMClient.parse_verdict({"id": 7, "status": "SUCCESS", "mag": 15.2, "mag_err": 0.05})
    assert verdict.calib_id == 7 and verdict.mag == 15.2 and not verdict.is_limit


def test_parse_verdict_limit():
    verdict = BHTOMClient.parse_verdict({"id": 8, "status": "SUCCESS", "mag": 18.0, "mag_err": -1})
    assert verdict.is_limit


def test_parse_verdict_error_record():
    # shape verified against the live service (dry-run ids are never stored)
    verdict = BHTOMClient.parse_verdict({"Error": "File with id 1454270 does not exist"})
    assert verdict.status == "ERROR"
    assert "does not exist" in verdict.message


def test_extract_ids_live_upload_shape():
    # exact success shape captured from the live upload service
    payload = {"Success": [{"file name:": "416_x.fits", "id": "1454270", "message": "Received plain FITS file."}]}
    assert _extract_ids(payload) == [1454270]


# ---------------------------------------------------------------------------
# error taxonomy / retries
# ---------------------------------------------------------------------------

@responses.activate
def test_server_error(client):
    responses.post(f"{BASE}/targets/getTargetList/", status=502)
    with pytest.raises(ServerError):
        client.get_targets(name="X")


@responses.activate
def test_auth_error_on_401(client):
    responses.post(f"{BASE}/observatory/getObservatoryList/", status=401, json={"detail": "no"})
    with pytest.raises(AuthError):
        client.get_observatories()


@responses.activate
def test_connection_error_becomes_network_error(client):
    import requests as _requests

    responses.post(
        f"{BASE}/targets/getTargetList/", body=_requests.ConnectionError("refused")
    )
    with pytest.raises(NetworkError):
        client.get_targets(name="X")


def test_extract_ids_handles_shapes():
    assert _extract_ids({"files": [{"id": 1}, {"id": 2}]}) == [1, 2]
    assert _extract_ids([{"calib_id": "9"}]) == [9]
    assert _extract_ids({"result": {"dataproduct_id": 5, "nested": [{"id": 5}]}}) == [5]
    assert _extract_ids({"message": "ok"}) == []


def test_observatory_list_shapes(client):
    from bhtom_uploader.core.bhtom import _as_list

    assert _as_list([{"name": "a"}]) == [{"name": "a"}]
    assert _as_list({"results": [{"name": "b"}]}) == [{"name": "b"}]
    assert _as_list({"unrelated": 1}) == []
