"""Filesystem paths used by data loaders and offline scripts."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STANDARD_DATA_DIR = PROJECT_ROOT / "standard-data"

