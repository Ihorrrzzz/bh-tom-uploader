"""Light-curve parsing + rendering.

BHTOM's photometry download is semicolon-separated text:
``MJD;Magnitude;Error;Facility;Filter;Observer``.

Two renderers:
* ``render_thumbnail`` - matplotlib (Agg) PNG for the completion toast
  (kaleido deliberately avoided: its 1.x line requires an external Chrome);
* ``render_interactive_html`` - plotly HTML for "open in browser".

Colors are assigned stably per (facility, filter) - same series, same color,
every time (the old app used random colors per observer).
"""
from __future__ import annotations

import colorsys
import hashlib
import io
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # render off-screen; never touches the Qt event loop
import matplotlib.pyplot as plt  # noqa: E402


@dataclass
class PhotometryPoint:
    mjd: float
    mag: float
    err: float
    facility: str
    filter_name: str
    observer: str

    @property
    def series(self) -> str:
        return f"{self.facility} {self.filter_name}".strip()

    @property
    def is_limit(self) -> bool:
        return self.err < 0  # BHTOM convention: negative error = limiting magnitude


def parse_photometry(text: str) -> list[PhotometryPoint]:
    points: list[PhotometryPoint] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("mjd"):
            continue
        fields = line.split(";")
        if len(fields) < 6:
            continue
        try:
            mjd, mag, err = float(fields[0]), float(fields[1]), float(fields[2])
        except ValueError:
            continue
        points.append(PhotometryPoint(mjd, mag, err, fields[3].strip(),
                                      fields[4].strip(), fields[5].strip()))
    return points


def series_color(key: str) -> str:
    """Deterministic, distinguishable color for a series name."""
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    hue = digest[0] / 255.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.85)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _grouped(points: list[PhotometryPoint]) -> dict[str, list[PhotometryPoint]]:
    groups: dict[str, list[PhotometryPoint]] = {}
    for p in points:
        groups.setdefault(p.series, []).append(p)
    return groups


def render_thumbnail(
    points: list[PhotometryPoint],
    target: str,
    dark: bool = True,
    size: tuple[int, int] = (360, 230),
) -> bytes:
    """PNG bytes for the toast thumbnail (theme-aware)."""
    bg = "#1C1D20" if dark else "#FFFFFF"
    fg = "#E6E6E8" if dark else "#1B1C1E"
    grid = "#3A3C40" if dark else "#D9D9DE"

    dpi = 100
    fig, ax = plt.subplots(figsize=(size[0] / dpi, size[1] / dpi), dpi=dpi)
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)

    if points:
        for series, pts in sorted(_grouped(points).items()):
            color = series_color(series)
            detections = [p for p in pts if not p.is_limit]
            limits = [p for p in pts if p.is_limit]
            if detections:
                ax.errorbar(
                    [p.mjd for p in detections], [p.mag for p in detections],
                    yerr=[p.err for p in detections],
                    fmt="o", ms=2.5, lw=0.7, elinewidth=0.6, capsize=0,
                    color=color, label=series,
                )
            if limits:
                ax.scatter([p.mjd for p in limits], [p.mag for p in limits],
                           marker="v", s=9, color=color, alpha=0.6)
        ax.invert_yaxis()
        if len(_grouped(points)) <= 4:
            ax.legend(fontsize=5.5, frameon=False, labelcolor=fg)
    else:
        ax.text(0.5, 0.5, "no photometry yet", transform=ax.transAxes,
                ha="center", va="center", color=fg, fontsize=9)

    ax.set_title(target, color=fg, fontsize=8)
    ax.set_xlabel("MJD", color=fg, fontsize=6.5)
    ax.set_ylabel("mag", color=fg, fontsize=6.5)
    ax.tick_params(colors=fg, labelsize=6)
    for spine in ax.spines.values():
        spine.set_color(grid)
    ax.grid(True, color=grid, alpha=0.4, lw=0.4)
    fig.tight_layout(pad=0.9)

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=bg)
    plt.close(fig)
    return buffer.getvalue()


def find_period(points: list[PhotometryPoint]) -> Optional[float]:
    """Lomb-Scargle best period in days, or None when the data can't support one.

    Search window follows the author's ml_lightcurve_practice recipe:
    0.2 d … min(60 d, 0.9×time span), samples_per_peak=5, nyquist_factor=3.
    """
    detections = [p for p in points if not p.is_limit]
    if len(detections) < 10:
        return None
    import numpy as np
    from astropy.timeseries import LombScargle

    t = np.array([p.mjd for p in detections])
    m = np.array([p.mag for p in detections])
    e = np.array([max(p.err, 1e-3) for p in detections])
    span = float(t.max() - t.min())
    if span < 1.0 or np.ptp(m) == 0.0:
        return None
    min_period, max_period = 0.2, min(60.0, 0.9 * span)
    if max_period <= min_period:
        return None
    try:
        ls = LombScargle(t, m - m.mean(), e)
        frequency, power = ls.autopower(
            minimum_frequency=1.0 / max_period,
            maximum_frequency=1.0 / min_period,
            samples_per_peak=5,
            nyquist_factor=3,
        )
        if len(power) == 0:
            return None
        return float(1.0 / frequency[power.argmax()])
    except Exception:
        return None


def render_interactive_html(points: list[PhotometryPoint], target: str) -> Path:
    """Standalone interactive plotly page (time series + folded view when a
    Lomb-Scargle period is found) in a temp file; returns its path."""
    import plotly.graph_objs as go
    import plotly.io as pio

    fig = go.Figure()
    for series, pts in sorted(_grouped(points).items()):
        color = series_color(series)
        detections = [p for p in pts if not p.is_limit]
        limits = [p for p in pts if p.is_limit]
        if detections:
            fig.add_trace(go.Scatter(
                x=[p.mjd for p in detections], y=[p.mag for p in detections],
                error_y=dict(type="data", array=[p.err for p in detections],
                             visible=True, color=color),
                mode="markers", name=series, marker=dict(color=color, size=5),
            ))
        if limits:
            fig.add_trace(go.Scatter(
                x=[p.mjd for p in limits], y=[p.mag for p in limits],
                mode="markers", name=f"{series} (limits)",
                marker=dict(color=color, size=7, symbol="triangle-down", opacity=0.6),
            ))
    fig.update_layout(
        title=f"{target} - BHTOM photometry",
        xaxis_title="MJD",
        yaxis_title="Magnitude",
        yaxis_autorange="reversed",
        legend_title="Facility / Filter",
        template="plotly_white",
    )

    html_parts = [pio.to_html(fig, full_html=False, include_plotlyjs=True)]

    period = find_period(points)
    if period is not None:
        folded = go.Figure()
        for series, pts in sorted(_grouped(points).items()):
            detections = [p for p in pts if not p.is_limit]
            if not detections:
                continue
            phase = [(p.mjd / period) % 1.0 for p in detections]
            folded.add_trace(go.Scatter(
                x=phase, y=[p.mag for p in detections],
                error_y=dict(type="data", array=[p.err for p in detections], visible=True,
                             color=series_color(series)),
                mode="markers", name=series,
                marker=dict(color=series_color(series), size=5),
            ))
        folded.update_layout(
            title=f"{target} - folded at P = {period:.4f} d (Lomb-Scargle)",
            xaxis_title="Phase",
            yaxis_title="Magnitude",
            yaxis_autorange="reversed",
            template="plotly_white",
        )
        html_parts.append(pio.to_html(folded, full_html=False, include_plotlyjs=False))

    page = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{target} - BHTOM photometry</title></head><body>"
        + "".join(html_parts)
        + "</body></html>"
    )
    handle = tempfile.NamedTemporaryFile(
        delete=False, suffix=".html", prefix="bhtom_lc_"
    )
    with handle:
        handle.write(page.encode("utf-8"))
    return Path(handle.name)
