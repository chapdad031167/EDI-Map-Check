"""Shared fixtures: paths to the synthetic example artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"


@pytest.fixture(scope="session")
def examples_dir() -> Path:
    return EXAMPLES


@pytest.fixture(scope="session")
def reference_spec_path() -> Path:
    return EXAMPLES / "specs" / "850_reference_spec.xlsx"
