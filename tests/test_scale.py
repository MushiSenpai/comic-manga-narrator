"""Phase 7 tests — PDF splitting and chapter grouping."""

from pathlib import Path

import fitz
import pytest

from comic_narrator.scale import split_pdf, group_chapters


@pytest.fixture
def three_page_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "book.pdf"
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=339, height=545)
        page.insert_text((50, 100), f"Page {i + 1}")
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def test_split_pdf_renders_all_pages(three_page_pdf, tmp_path):
    pages_dir = tmp_path / "pages"
    out = split_pdf(three_page_pdf, pages_dir, dpi=72)
    assert [p.name for p in out] == ["page_0001.jpg", "page_0002.jpg", "page_0003.jpg"]
    assert all(p.exists() and p.stat().st_size > 0 for p in out)


def test_split_pdf_is_resumable(three_page_pdf, tmp_path):
    pages_dir = tmp_path / "pages"
    first = split_pdf(three_page_pdf, pages_dir, dpi=72)
    mtimes = [p.stat().st_mtime_ns for p in first]
    second = split_pdf(three_page_pdf, pages_dir, dpi=72)
    assert second == first
    # Existing renders are not redone
    assert [p.stat().st_mtime_ns for p in second] == mtimes


def test_group_chapters_no_splits():
    assert group_chapters(5, None) == [[1, 2, 3, 4, 5]]
    assert group_chapters(5, []) == [[1, 2, 3, 4, 5]]


def test_group_chapters_with_splits():
    assert group_chapters(6, [3, 5]) == [[1, 2], [3, 4], [5, 6]]


def test_group_chapters_ignores_out_of_range_and_duplicates():
    # 1 is not a valid split (chapter 1 always starts at page 1); 99 is beyond the book
    assert group_chapters(4, [1, 3, 3, 99]) == [[1, 2], [3, 4]]


def test_group_chapters_single_page_chapters():
    assert group_chapters(3, [2, 3]) == [[1], [2], [3]]
