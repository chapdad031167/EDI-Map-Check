"""Shared fixtures: paths to the synthetic example artifacts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"

# app.py lives at the repo root (not in the installed package); make it
# importable under a bare `pytest` invocation, which does not add the CWD.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session")
def examples_dir() -> Path:
    return EXAMPLES


@pytest.fixture(scope="session")
def reference_spec_path() -> Path:
    return EXAMPLES / "specs" / "850_reference_spec.xlsx"
