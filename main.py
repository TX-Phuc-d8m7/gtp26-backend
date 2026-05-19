"""Compatibility entrypoint.

Prefer running `app.main:app` after the refactor. This file keeps existing
commands such as `uvicorn main:app` working during the transition.
"""

from app.main import app  # noqa: F401

