"""Pass 1a: OpenCV panel detection — contour-based, gutter-aware."""

from __future__ import annotations

import cv2
import numpy as np
from pathlib import Path

from comic_narrator.schemas import BBox, Panel, PagePanels


def detect_panels(
    image_path: Path,
    min_area_frac: float = 0.01,
    gutter_thresh: int = 10,
) -> PagePanels:
    """
    Detect comic panel bounding boxes from a page image.

    Algorithm:
    1. Convert to grayscale, threshold to binary (inverted for dark gutters).
    2. Dilate to close small gaps within panels.
    3. Find external contours → bounding rectangles.
    4. Filter by minimum area (ignore small artifacts).
    5. Sort by y-position (top→bottom), then x depending on layout.
    6. Assign order_index after reading_order module runs.

    Returns PagePanels with bboxes but order_index=0 (reading_order sets final order).
    """
    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")

    h, w = img.shape[:2]
    min_area = int(w * h * min_area_frac)

    # Grayscale + threshold
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Invert: gutters are typically white/light; panels are darker
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    # Dilate to close small text/art gaps within panels
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dilated = cv2.dilate(binary, kernel, iterations=2)

    # Find contours
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    panels: list[Panel] = []
    for i, cnt in enumerate(contours):
        x, y, bw, bh = cv2.boundingRect(cnt)
        area = bw * bh
        if area < min_area:
            continue
        # Expand slightly to capture edges
        margin = gutter_thresh // 2
        x = max(0, x - margin)
        y = max(0, y - margin)
        bw = min(w - x, bw + 2 * margin)
        bh = min(h - y, bh + 2 * margin)
        panels.append(Panel(id=i + 1, bbox=BBox(x=x, y=y, w=bw, h=bh), order_index=0))

    if not panels:
        # Fallback: treat entire image as one panel
        panels.append(Panel(id=1, bbox=BBox(x=0, y=0, w=w, h=h), order_index=0))

    return PagePanels(layout="manga", panels=panels)


def extract_panel_image(image_path: Path, bbox: BBox, output_dir: Path) -> Path:
    """Crop a panel region from the page and save as a standalone image."""
    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")

    h, w = img.shape[:2]
    # Clamp bbox to image bounds
    x1 = max(0, bbox.x)
    y1 = max(0, bbox.y)
    x2 = min(w, bbox.x + bbox.w)
    y2 = min(h, bbox.y + bbox.h)

    crop = img[y1:y2, x1:x2]
    out_path = output_dir / f"panel_{bbox.x}_{bbox.y}.jpg"
    cv2.imwrite(str(out_path), crop)
    return out_path
