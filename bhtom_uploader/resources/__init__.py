"""Bundled static resources (icons, logo)."""
from pathlib import Path


def resource_path(name: str) -> Path:
    return Path(__file__).resolve().parent / name
