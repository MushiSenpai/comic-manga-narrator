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


def test_collect_pages_from_cbz(tmp_path):
    import zipfile
    from PIL import Image
    from comic_narrator.scale import collect_pages

    cbz = tmp_path / "book.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        for name in ("p2.jpg", "p1.jpg", "notes.txt"):
            if name.endswith(".jpg"):
                img_path = tmp_path / name
                Image.new("RGB", (100, 150), "white").save(img_path)
                zf.write(img_path, name)
            else:
                zf.writestr(name, "ignore me")
    pages = collect_pages(cbz, tmp_path / "pages")
    # Image members only, name-sorted (p1 before p2), renumbered
    assert [p.name for p in pages] == ["page_0001.jpg", "page_0002.jpg"]
    assert all(p.exists() for p in pages)


def test_collect_pages_from_directory(tmp_path):
    from PIL import Image
    from comic_narrator.scale import collect_pages

    src = tmp_path / "scans"
    src.mkdir()
    for name in ("b.png", "a.jpg"):
        Image.new("RGB", (80, 120), "white").save(src / name)
    (src / "cover.txt").write_text("not an image")
    pages = collect_pages(src, tmp_path / "pages")
    assert [p.name for p in pages] == ["page_0001.jpg", "page_0002.png"]


def test_collect_pages_rejects_fake_cbr(tmp_path):
    import pytest as _pytest
    from comic_narrator.scale import collect_pages
    bad = tmp_path / "book.cbr"
    bad.write_bytes(b"Rar!\x1a\x07\x00 not a zip")
    with _pytest.raises(ValueError, match="unrar|cbz"):
        collect_pages(bad, tmp_path / "pages")


def test_prior_voice_map_keeps_character_voice():
    from comic_narrator.build_script import build_script
    from comic_narrator.schemas import (
        BBox, Character, Dialogue, PageAnalysis, PagePanels, Panel, PanelAnalysis,
    )
    analysis = PageAnalysis(
        layout="manga",
        panels_layout=PagePanels(layout="manga", panels=[
            Panel(id=1, bbox=BBox(x=0, y=0, w=100, h=100), order_index=0)]),
        panels_analysis=[PanelAnalysis(
            panel_id=1,
            characters=[Character(label="luffy", voice_attributes=["male", "young"],
                                  voice_type="human", is_speaking=True)],
            dialogues=[Dialogue(speaker="luffy", text="Yo!", tone="neutral")],
        )],
    )
    # Page 50: the book map already assigned luffy a non-default voice
    script, cast = build_script(analysis, prior_voice_map={"luffy": "ja_m_twenties_2e8835"})
    dia = [e for e in script.events if e.kind.value == "dialogue"][0]
    assert dia.voice_id == "ja_m_twenties_2e8835"


def test_panel_detection_rejects_bubbles(tmp_path):
    """A speech-bubble-sized region must NOT become a panel (the
    'zoom into the speech bubble' defect on webtoon segments)."""
    from PIL import Image, ImageDraw
    from comic_narrator.vision.panels import detect_panels
    # 850x1600 segment: one big panel + two tiny bubble rectangles
    img = Image.new("RGB", (850, 1600), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((20, 20, 830, 1100), outline="black", width=6)      # real panel
    d.rectangle((62, 377, 407, 445), fill="white", outline="black", width=3)  # bubble 345x68
    d.rectangle((275, 445, 583, 520), fill="white", outline="black", width=3)  # bubble 308x75
    p = tmp_path / "seg.png"
    img.save(p)
    panels = detect_panels(p).panels
    for pan in panels:
        # No panel should be bubble-sized (tiny on both axes)
        assert not (pan.bbox.w < 0.25 * 850 and pan.bbox.h < 0.25 * 1600), \
            f"bubble leaked as panel: {pan.bbox}"
