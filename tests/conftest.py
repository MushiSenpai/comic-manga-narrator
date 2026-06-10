"""Shared test fixtures."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def one_piece_page() -> Path:
    """Path to the canonical One Piece test page."""
    path = FIXTURES_DIR / "one_piece_page.jpg"
    if not path.exists():
        pytest.skip("one_piece_page.jpg not available (placeholder until real scan)")
    return path
