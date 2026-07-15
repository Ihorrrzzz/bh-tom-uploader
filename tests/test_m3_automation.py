"""M3: upload journal, light-curve parse/render, watcher stability, journal-in-pipeline."""
from __future__ import annotations

import time

import numpy as np
import pytest
import responses

from bhtom_uploader.core.journal import UploadJournal
from bhtom_uploader.core.lightcurve import (
    parse_photometry,
    render_interactive_html,
    render_thumbnail,
    series_color,
)

from fixtures import make_light, write_fits, SHAPE

PHOT_TEXT = (
    "MJD;Magnitude;Error;Facility;Filter;Observer\n"
    "60000.5;15.20;0.03;AZT-8;GaiaSP/V;ihor\n"
    "60001.5;15.25;0.04;AZT-8;GaiaSP/V;ihor\n"
    "60002.5;18.00;-1;AZT-8;GaiaSP/V;ihor\n"        # limit (negative error)
    "60000.7;15.60;0.05;ROAD;GaiaSP/R;someone\n"
    "garbage line\n"
    "60003.1;bad;0.05;X;Y;z\n"
)


# ---------------------------------------------------------------------------
# journal
# ---------------------------------------------------------------------------

def test_journal_records_and_skips(tmp_path):
    source = tmp_path / "light.fits"
    source.write_bytes(b"data")
    journal = UploadJournal(tmp_path / "journal.json")

    assert not journal.already_uploaded(source, "Gaia22awa")
    journal.record(source, "Gaia22awa", [123])
    assert journal.already_uploaded(source, "Gaia22awa")
    assert journal.already_uploaded(source, "gaia22awa")      # case-insensitive target
    assert not journal.already_uploaded(source, "OtherTarget")  # different target -> new upload


def test_journal_persists_across_instances(tmp_path):
    source = tmp_path / "a.fits"
    source.write_bytes(b"x")
    UploadJournal(tmp_path / "j.json").record(source, "T", [1])
    assert UploadJournal(tmp_path / "j.json").already_uploaded(source, "T")


def test_journal_invalidated_by_file_change(tmp_path):
    source = tmp_path / "b.fits"
    source.write_bytes(b"version one")
    journal = UploadJournal(tmp_path / "j.json")
    journal.record(source, "T", [1])
    time.sleep(1.1)  # ensure mtime changes at 1s resolution
    source.write_bytes(b"version two -- different size too")
    assert not journal.already_uploaded(source, "T")


def test_journal_missing_file_is_not_uploaded(tmp_path):
    journal = UploadJournal(tmp_path / "j.json")
    assert not journal.already_uploaded(tmp_path / "nope.fits", "T")


# ---------------------------------------------------------------------------
# light curve
# ---------------------------------------------------------------------------

def test_parse_photometry():
    points = parse_photometry(PHOT_TEXT)
    assert len(points) == 4  # header + garbage + bad-float lines skipped
    assert points[0].mjd == 60000.5 and points[0].mag == 15.20
    assert points[2].is_limit
    assert {p.series for p in points} == {"AZT-8 GaiaSP/V", "ROAD GaiaSP/R"}


def test_series_color_stable_and_hexy():
    c1 = series_color("AZT-8 GaiaSP/V")
    assert c1 == series_color("AZT-8 GaiaSP/V")  # deterministic
    assert c1.startswith("#") and len(c1) == 7
    assert c1 != series_color("ROAD GaiaSP/R")


@pytest.mark.parametrize("dark", [True, False])
def test_render_thumbnail_png(dark):
    png = render_thumbnail(parse_photometry(PHOT_TEXT), "TestTarget", dark=dark)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 4000


def test_render_thumbnail_empty_data():
    png = render_thumbnail([], "Empty", dark=True)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_interactive_html(tmp_path):
    path = render_interactive_html(parse_photometry(PHOT_TEXT), "TestTarget")
    try:
        html = path.read_text(encoding="utf-8")
        assert "<html" in html.lower() and "plotly" in html.lower()
        assert "TestTarget" in html
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# watcher stability sweep (no real watchdog events needed)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qcore_app():
    from PySide6.QtCore import QCoreApplication

    return QCoreApplication.instance() or QCoreApplication([])


def test_watcher_promotes_stable_readable_file(tmp_path, qcore_app):
    from bhtom_uploader.core.watcher import FolderWatcher

    rng = np.random.default_rng(1)
    path = make_light(tmp_path / "new_light.fits", rng)

    watcher = FolderWatcher(tmp_path, stable_checks=2)
    ready: list = []
    watcher.file_ready.connect(ready.append)

    watcher._on_fs_event(str(path))
    for _ in range(4):  # size/mtime identical each sweep -> stable after N checks
        watcher._sweep()
    assert ready and ready[0] == path


def test_watcher_ignores_growing_file(tmp_path, qcore_app):
    from bhtom_uploader.core.watcher import FolderWatcher

    path = tmp_path / "growing.fits"
    path.write_bytes(b"x" * 100)
    watcher = FolderWatcher(tmp_path, stable_checks=2)
    ready: list = []
    watcher.file_ready.connect(ready.append)

    watcher._on_fs_event(str(path))
    watcher._sweep()
    path.write_bytes(b"x" * 200)  # still growing between sweeps
    watcher._sweep()
    path.write_bytes(b"x" * 300)
    watcher._sweep()
    assert not ready


def test_watcher_ignores_irrelevant_paths(tmp_path, qcore_app):
    from bhtom_uploader.core.watcher import FolderWatcher

    watcher = FolderWatcher(tmp_path, stable_checks=1)
    assert not watcher._relevant(tmp_path / "notes.txt")
    assert not watcher._relevant(tmp_path / "Calibrated files" / "calibrated_x.fits")
    assert not watcher._relevant(tmp_path.parent / "outside.fits")
    assert watcher._relevant(tmp_path / "night" / "img.fits")


def test_watcher_gives_up_on_unreadable(tmp_path, qcore_app):
    from bhtom_uploader.core import watcher as watcher_mod
    from bhtom_uploader.core.watcher import FolderWatcher

    bad = tmp_path / "broken.fits"
    bad.write_bytes(b"never a FITS file")
    watcher = FolderWatcher(tmp_path, stable_checks=1)
    errors: list = []
    watcher.watch_error.connect(errors.append)

    watcher._on_fs_event(str(bad))
    for _ in range(watcher_mod.MAX_OPEN_ATTEMPTS + 3):
        watcher._sweep()
    assert errors and "broken.fits" in errors[0]


# ---------------------------------------------------------------------------
# journal wired into the pipeline
# ---------------------------------------------------------------------------

@responses.activate
def test_pipeline_skips_journaled_and_records_new(tmp_path, qcore_app):
    from bhtom_uploader.core.bhtom import BHTOMClient
    from bhtom_uploader.core.pipeline import Pipeline, RunOptions
    from bhtom_uploader.core.scanner import scan_directory

    responses.post("https://up.test/upload/", json={"Success": [{"id": 11}]})
    rng = np.random.default_rng(2)
    old = make_light(tmp_path / "old.fits", rng, CALSTAT="BDF")
    new = make_light(tmp_path / "new.fits", rng, CALSTAT="BDF")

    journal = UploadJournal(tmp_path / "j.json")
    journal.record(old, "T", [99])  # 'old' was uploaded in a previous run

    client = BHTOMClient(base_url="https://b.test", upload_url="https://up.test")
    client.token = "t"
    scan = scan_directory(tmp_path)
    pipeline = Pipeline(scan, RunOptions(target="T", observatory="OB"), client, journal=journal)
    reports: list = []
    pipeline.finished.connect(reports.append)
    pipeline.run()

    report = reports[0]
    assert report.n_skipped == 1 and report.n_success == 1
    skipped = next(i for i in report.items if i.source == old)
    assert "journal" in skipped.message
    assert len(responses.calls) == 1          # only 'new' hit the network
    assert journal.already_uploaded(new, "T")  # and got recorded
