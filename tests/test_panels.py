"""Tests for OpenCV panel detection and reading order."""

import cv2
import numpy as np
from pathlib import Path

from comic_narrator.vision.panels import detect_panels
from comic_narrator.vision.reading_order import assign_reading_order


def _make_test_page(n_panels: int = 3, layout: str = "manga") -> Path:
    """Generate a synthetic comic page with white panels on gray background."""
    w, h = 800, 1200
    img = np.full((h, w, 3), 240, dtype=np.uint8)  # light background

    if n_panels == 3:
        # Three panels stacked vertically
        panel_h = 350
        gutter = 25
        for i in range(3):
            y = 20 + i * (panel_h + gutter)
            img[y:y+panel_h, 20:w-20] = 50   # dark panel fill
            # draw dark border
            cv2.rectangle(img, (20, y), (w-21, y+panel_h), (0, 0, 0), 3)
    elif n_panels == 1:
        img[50:h-50, 50:w-50] = 50
        cv2.rectangle(img, (50, 50), (w-51, h-51), (0, 0, 0), 3)

    out = Path("/tmp/test_comic_page.jpg")
    cv2.imwrite(str(out), img)
    return out


def test_detect_three_panels():
    """Should detect 3 panels in a vertical stack layout."""
    page = _make_test_page(3)
    result = detect_panels(page, min_area_frac=0.005, gutter_thresh=30)
    assert len(result.panels) == 3, f"Expected 3 panels, got {len(result.panels)}"


def test_fallback_single_panel():
    """Should return 1 panel when detection finds nothing (whole page fallback)."""
    # Create a solid gray image with no clear panels
    img = np.full((800, 600, 3), 128, dtype=np.uint8)
    out = Path("/tmp/test_solid.jpg")
    cv2.imwrite(str(out), img)
    result = detect_panels(out, min_area_frac=0.5)  # high threshold
    assert len(result.panels) == 1, "Fallback should produce 1 panel"


def test_reading_order_manga():
    """Manga reading order: right→left within rows, top→bottom."""
    from comic_narrator.schemas import BBox, Panel, PagePanels

    # Simulate 4 panels in 2 rows × 2 columns (typical manga layout)
    # Row 1: panel 1 (right), panel 2 (left)
    # Row 2: panel 3 (right), panel 4 (left)
    panels = PagePanels(layout="manga", panels=[
        Panel(id=1, bbox=BBox(x=400, y=0, w=400, h=500), order_index=0),   # right, row 1
        Panel(id=2, bbox=BBox(x=0, y=0, w=400, h=500), order_index=0),     # left, row 1
        Panel(id=3, bbox=BBox(x=400, y=550, w=400, h=500), order_index=0), # right, row 2
        Panel(id=4, bbox=BBox(x=0, y=550, w=400, h=500), order_index=0),   # left, row 2
    ])
    result = assign_reading_order(panels, "manga")
    order = [p.id for p in result.panels]
    # Expected: panel 1 (top-right) → panel 2 (top-left) → panel 3 (bottom-right) → panel 4 (bottom-left)
    assert order == [1, 2, 3, 4], f"Got {order}, expected [1,2,3,4]"


def test_reading_order_western():
    """Western reading order: left→right within rows, top→bottom."""
    from comic_narrator.schemas import BBox, Panel, PagePanels

    panels = PagePanels(layout="western", panels=[
        Panel(id=1, bbox=BBox(x=0, y=0, w=400, h=500), order_index=0),
        Panel(id=2, bbox=BBox(x=400, y=0, w=400, h=500), order_index=0),
        Panel(id=3, bbox=BBox(x=0, y=550, w=400, h=500), order_index=0),
        Panel(id=4, bbox=BBox(x=400, y=550, w=400, h=500), order_index=0),
    ])
    result = assign_reading_order(panels, "western")
    order = [p.id for p in result.panels]
    assert order == [1, 2, 3, 4], f"Got {order}, expected [1,2,3,4]"
