"""Typed BHTOM REST API client.

Endpoints per the official docs (bhtom2 Documentation/DocumentationAPI.md):
auth, current user, observatory list/favourites, target list/create,
data-product upload, calibration results, photometry download, data products.

Error taxonomy lets the pipeline/UI react precisely instead of string-matching
server messages (the old client's failure mode).

Retry policy: read-style calls retry on connection errors; uploads never
auto-retry (a retried POST could duplicate data points).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import requests

from .models import CalibVerdict
from .settings import get_bhtom_url, get_upload_url

DEFAULT_TIMEOUT = 30
UPLOAD_TIMEOUT = 300  # large FITS files over slow observatory links
RETRY_BACKOFF_S = 2.0


class BHTOMError(Exception):
    """Base for all BHTOM client errors."""


class NetworkError(BHTOMError):
    """Could not reach the service (connection error / timeout)."""


class AuthError(BHTOMError):
    """Bad credentials or invalid/expired token."""


class ValidationError(BHTOMError):
    """The server rejected the request payload (HTTP 400)."""

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.details = details


class TargetMissingError(BHTOMError):
    """The named target does not exist in BHTOM."""

    def __init__(self, target: str, message: str = "") -> None:
        super().__init__(message or f"target '{target}' does not exist in BHTOM")
        self.target = target


class ServerError(BHTOMError):
    """HTTP 5xx from the service."""


def _safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {}


def _as_list(payload: Any) -> list:
    """Normalize the various list response shapes BHTOM endpoints return."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "data", "targets", "observatories", "list", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _extract_ids(payload: Any) -> list[int]:
    """Best-effort recursive extraction of uploaded file / calibration ids."""
    ids: list[int] = []
    id_keys = {"id", "calib_id", "calibid", "dataproduct_id", "file_id"}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() in id_keys and isinstance(value, (int, str)):
                    try:
                        ids.append(int(value))
                    except (TypeError, ValueError):
                        pass
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    # de-duplicate, preserve order
    seen: set[int] = set()
    return [i for i in ids if not (i in seen or seen.add(i))]


class BHTOMClient:
    def __init__(
        self,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        upload_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = (base_url or get_bhtom_url()).rstrip("/")
        self.upload_url = (upload_url or get_upload_url()).rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self._token: Optional[str] = None
        self.token = token

    # ------------------------------------------------------------------
    @property
    def token(self) -> Optional[str]:
        return self._token

    @token.setter
    def token(self, value: Optional[str]) -> None:
        self._token = value
        if value:
            self.session.headers["Authorization"] = f"Token {value}"
        else:
            self.session.headers.pop("Authorization", None)

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------

    def _request(
        self, method: str, url: str, *, retries: int = 2, timeout: Optional[float] = None, **kwargs
    ) -> requests.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                return self.session.request(method, url, timeout=timeout or self.timeout, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(RETRY_BACKOFF_S * (attempt + 1))
        raise NetworkError(f"cannot reach {url}: {last_exc}") from last_exc

    def _raise_for_status(self, response: requests.Response) -> None:
        if response.ok:
            return
        payload = _safe_json(response)
        detail = payload if payload else response.text[:500]
        if response.status_code in (401, 403):
            raise AuthError(f"authentication failed ({response.status_code}): {detail}")
        if response.status_code == 400:
            raise ValidationError(f"request rejected: {detail}", details=payload)
        if response.status_code >= 500:
            raise ServerError(f"BHTOM server error {response.status_code}")
        raise BHTOMError(f"unexpected HTTP {response.status_code}: {detail}")

    def _post_json(self, path: str, payload: dict, *, retries: int = 2) -> Any:
        response = self._request("POST", f"{self.base_url}{path}", json=payload, retries=retries)
        self._raise_for_status(response)
        return _safe_json(response)

    # ------------------------------------------------------------------
    # auth / identity
    # ------------------------------------------------------------------

    def login(self, username: str, password: str) -> str:
        """Exchange username+password for an API token (and adopt it)."""
        response = self._request(
            "POST",
            f"{self.base_url}/api/token-auth/",
            json={"username": username, "password": password},
        )
        if response.status_code == 400:
            raise AuthError("invalid username or password")
        self._raise_for_status(response)
        token = _safe_json(response).get("token")
        if not token:
            raise BHTOMError("login response contained no token")
        self.token = token
        return token

    def me(self) -> dict:
        """Identity behind the current token - also serves as token validation."""
        response = self._request("GET", f"{self.base_url}/common/api/users/me/")
        self._raise_for_status(response)
        return _safe_json(response) or {}

    # ------------------------------------------------------------------
    # observatories
    # ------------------------------------------------------------------

    def get_observatories(self, page: int = 1) -> list[dict]:
        return _as_list(self._post_json("/observatory/getObservatoryList/", {"page": page}))

    def get_favourite_observatories(self) -> list[dict]:
        return _as_list(self._post_json("/observatory/getFavouriteObservatory/", {}))

    def add_favourite_observatory(self, oname: str, comment: str = "") -> dict:
        """Add a camera (by ONAME) to the user's favourites.

        The upload service only accepts observatories from the user's own list
        (verified live: 'Observatory with camera doesn't exist on your list'),
        so the app adds the picked camera on demand.
        """
        payload: dict[str, Any] = {"oname": oname}
        if comment:
            payload["comment"] = comment
        return self._post_json("/observatory/addFavouriteObservatory/", payload, retries=0) or {}

    # ------------------------------------------------------------------
    # targets
    # ------------------------------------------------------------------

    def get_targets(self, name: Optional[str] = None, page: int = 1, **filters) -> list[dict]:
        payload: dict[str, Any] = {"page": page, **filters}
        if name:
            payload["name"] = name
        return _as_list(self._post_json("/targets/getTargetList/", payload))

    def target_exists(self, name: str) -> bool:
        matches = self.get_targets(name=name)
        wanted = name.strip().lower()
        return any(str(t.get("name", "")).strip().lower() == wanted for t in matches)

    def create_target(
        self,
        name: str,
        ra: float,
        dec: float,
        epoch: float = 2000.0,
        classification: str = "Unknown",
        discovery_date: Optional[str] = None,
        importance: float = 9.9,
        cadence: float = 1.0,
        description: Optional[str] = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "name": name,
            "ra": ra,
            "dec": dec,
            "epoch": epoch,
            "classification": classification,
            "importance": importance,
            "cadence": cadence,
        }
        if discovery_date:
            payload["discovery_date"] = discovery_date
        if description:
            payload["description"] = description
        return self._post_json("/targets/createTarget/", payload, retries=0) or {}

    def download_photometry(self, name: str) -> str:
        """Semicolon-separated photometry: MJD;Magnitude;Error;Facility;Filter;Observer."""
        response = self._request(
            "POST", f"{self.base_url}/targets/download-photometry/", json={"name": name}
        )
        self._raise_for_status(response)
        return response.text

    def target_url(self, name: str) -> str:
        """Browser URL of the target page (for the toast's 'Open in browser')."""
        return f"{self.base_url}/targets/{name}/"

    # ------------------------------------------------------------------
    # upload + server-side calibration results
    # ------------------------------------------------------------------

    def upload_fits(
        self,
        path: Path,
        target: str,
        observatory: str,
        filter_name: str = "GaiaSP/any",
        dry_run: bool = False,
        comment: Optional[str] = None,
        observers: Optional[str] = None,
        data_product_type: str = "fits_file",
        mjd: Optional[float] = None,
    ) -> tuple[list[int], dict]:
        """Upload one file; returns (dataproduct/calibration ids, raw response).

        Never auto-retries: a duplicated POST would duplicate data points.
        """
        data: dict[str, Any] = {
            "target": target,
            "filter": filter_name,
            "data_product_type": data_product_type,
            "dry_run": "True" if dry_run else "False",
            "observatory": observatory,
        }
        if comment:
            data["comment"] = comment
        if observers:
            data["observers"] = observers
        if mjd is not None:
            data["mjd"] = mjd

        with open(path, "rb") as fh:
            response = self._request(
                "POST",
                f"{self.upload_url}/upload/",
                data=data,
                files={"files": fh},
                retries=0,
                timeout=UPLOAD_TIMEOUT,
            )

        payload = _safe_json(response)
        # A missing target is reported inside the payload. Shapes verified live:
        # legacy {'target': [...]} and current {'non_field_errors': ["Target 'X' does not exist."]}
        messages: list[str] = []
        if isinstance(payload, dict):
            for key in ("target", "non_field_errors"):
                value = payload.get(key)
                if isinstance(value, list):
                    messages.extend(str(m) for m in value)
        missing = [m for m in messages if "does not exist" in m.lower()]
        if missing:
            raise TargetMissingError(target, "; ".join(missing))
        self._raise_for_status(response)
        if isinstance(payload, dict) and "non_field_errors" in payload:
            raise ValidationError(str(payload["non_field_errors"]), details=payload)
        return _extract_ids(payload), payload if isinstance(payload, dict) else {"response": payload}

    def get_calibration_results(
        self,
        calib_ids: Optional[list[int]] = None,
        filenames: Optional[list[str]] = None,
        get_plot: bool = False,
        page: int = 1,
    ) -> list[dict]:
        payload: dict[str, Any] = {"getPlot": get_plot, "page": page}
        if calib_ids:
            payload["calibid"] = list(calib_ids)
        if filenames:
            payload["filename"] = list(filenames)
        result = self._post_json("/calibration/get-calibration-res/", payload)
        return _as_list(result) if not isinstance(result, list) else result

    @staticmethod
    def parse_verdict(record: dict) -> CalibVerdict:
        """Best-effort mapping of one calibration-result record to a verdict."""

        def first(*keys):
            for key in keys:
                if key in record and record[key] is not None:
                    return record[key]
            return None

        def as_float(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        # error records look like {"Error": "File with id N does not exist"} (verified live)
        error_text = record.get("Error") or record.get("error")

        mag_err = as_float(first("mag_err", "magerr", "mag_error"))
        calib_id = first("id", "calib_id", "calibid")
        try:
            calib_id = int(calib_id) if calib_id is not None else None
        except (TypeError, ValueError):
            calib_id = None
        return CalibVerdict(
            calib_id=calib_id,
            status=str(first("status", "calib_status", "state") or ("ERROR" if error_text else "")),
            mag=as_float(first("mag", "magnitude", "standardised_mag", "std_mag")),
            mag_err=mag_err,
            zp_error=as_float(first("zp_err", "zperr", "zp_error")),
            is_limit=(mag_err is not None and mag_err < 0),
            message=str(error_text or first("status_message", "message", "comment") or ""),
            raw=record,
        )

    # ------------------------------------------------------------------
    # data products (uploads history)
    # ------------------------------------------------------------------

    def list_data_products(self, page: int = 1, **filters) -> list[dict]:
        return _as_list(self._post_json("/common/api/data/", {"page": page, **filters}))
