"""Synthetic FITS generators with exactly known pixel math.

The physical model used everywhere:

    frame = BIAS_LEVEL + DARK_RATE * exptime + source_term + gaussian_noise

so a correct calibration must recover ``source_term / flat_shape_normalized``.
``FLAT_SHAPE`` has mean 1.0, which makes the expected calibrated light frame
a flat field of ``LIGHT_SIGNAL`` ADU.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.io import fits

SHAPE = (32, 32)
BIAS_LEVEL = 100.0
DARK_RATE = 2.0          # ADU / s
DARK_EXPTIME = 20.0      # deliberately != light exposure -> proves exposure scaling
FLAT_EXPTIME = 5.0
LIGHT_EXPTIME = 10.0
FLAT_LEVEL = 20000.0
LIGHT_SIGNAL = 500.0
NOISE_SIGMA = 1.0

# smooth vignetting-like gradient, mean exactly 1.0
FLAT_SHAPE = np.tile(np.linspace(0.8, 1.2, SHAPE[1]), (SHAPE[0], 1))
FLAT_SHAPE = FLAT_SHAPE / FLAT_SHAPE.mean()


def write_fits(path: Path, data, header: dict | None = None) -> Path:
    hdu = fits.PrimaryHDU(np.asarray(data, dtype=np.float32))
    for key, value in (header or {}).items():
        if key.upper() == "HISTORY":
            for line in value if isinstance(value, (list, tuple)) else [value]:
                hdu.header.add_history(line)
        else:
            hdu.header[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)
    return path


def _noise(rng: np.random.Generator) -> np.ndarray:
    return rng.normal(0.0, NOISE_SIGMA, SHAPE)


BASE_HEADER = {"XBINNING": 1, "YBINNING": 1, "CCD-TEMP": -10.0, "DATE-OBS": "2026-07-15T00:00:00"}


def make_bias(path: Path, rng: np.random.Generator, **extra) -> Path:
    header = {**BASE_HEADER, "IMAGETYP": "Bias Frame", "EXPTIME": 0.0, **extra}
    return write_fits(path, BIAS_LEVEL + _noise(rng), header)


def make_dark(path: Path, rng: np.random.Generator, exptime: float = DARK_EXPTIME, **extra) -> Path:
    header = {**BASE_HEADER, "IMAGETYP": "Dark Frame", "EXPTIME": exptime, **extra}
    return write_fits(path, BIAS_LEVEL + DARK_RATE * exptime + _noise(rng), header)


def make_flat(path: Path, rng: np.random.Generator, filter_name: str = "V", **extra) -> Path:
    header = {
        **BASE_HEADER,
        "IMAGETYP": "Flat Field",
        "EXPTIME": FLAT_EXPTIME,
        "FILTER": filter_name,
        **extra,
    }
    data = BIAS_LEVEL + DARK_RATE * FLAT_EXPTIME + FLAT_LEVEL * FLAT_SHAPE + _noise(rng)
    return write_fits(path, data, header)


def make_light(
    path: Path,
    rng: np.random.Generator,
    filter_name: str = "V",
    object_name: str = "TESTOBJ",
    exptime: float = LIGHT_EXPTIME,
    **extra,
) -> Path:
    header = {
        **BASE_HEADER,
        "IMAGETYP": "Light Frame",
        "EXPTIME": exptime,
        "FILTER": filter_name,
        "OBJECT": object_name,
        "RA": 123.456,
        "DEC": -45.678,
        **extra,
    }
    data = BIAS_LEVEL + DARK_RATE * exptime + LIGHT_SIGNAL * FLAT_SHAPE + _noise(rng)
    return write_fits(path, data, header)


def make_night(
    root: Path,
    n_bias: int = 3,
    n_dark: int = 3,
    n_flat: int = 3,
    n_light: int = 2,
    filter_name: str = "V",
    seed: int = 42,
) -> Path:
    """A complete synthetic observing night in one folder."""
    rng = np.random.default_rng(seed)
    for i in range(n_bias):
        make_bias(root / f"bias_{i:03d}.fits", rng)
    for i in range(n_dark):
        make_dark(root / f"dark_{i:03d}.fits", rng)
    for i in range(n_flat):
        make_flat(root / f"flat_{filter_name}_{i:03d}.fits", rng, filter_name=filter_name)
    for i in range(n_light):
        make_light(root / f"light_{i:03d}.fits", rng, filter_name=filter_name)
    return root
