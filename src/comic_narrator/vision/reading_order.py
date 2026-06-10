"""Pass 1b: Layout-aware reading-order sort.

Manga:   right→left within rows, top→bottom (rows sorted by topmost panel y)
Western: left→right within rows, top→bottom
"""

from __future__ import annotations

from comic_narrator.schemas import PagePanels


def assign_reading_order(panels: PagePanels, layout: str = "manga") -> PagePanels:
    """
    Sort panels by reading order and assign order_index.

    Algorithm:
    1. Sort all panels by y (top→bottom).
    2. Cluster into rows: panels whose y-centers overlap form a row.
    3. Within each row, sort by x:
       - manga:   descending x (right→left)
       - western: ascending  x (left→right)
    4. Flatten rows → assign sequential order_index.
    """
    if not panels.panels:
        return panels

    panel_list = list(panels.panels)

    # Sort by top y-position
    panel_list.sort(key=lambda p: p.bbox.y)

    rows: list[list] = []
    current_row: list = []
    current_row_y_center: float | None = None

    for panel in panel_list:
        panel_y_center = panel.bbox.y + panel.bbox.h / 2

        if current_row_y_center is None:
            current_row = [panel]
            current_row_y_center = panel_y_center
        else:
            # Check if this panel's y-center is within the current row's vertical span
            row_top = min(p.bbox.y for p in current_row)
            row_bottom = max(p.bbox.y + p.bbox.h for p in current_row)

            if panel.bbox.y < row_bottom and panel.bbox.y + panel.bbox.h > row_top:
                # Belongs to same row
                current_row.append(panel)
                current_row_y_center = sum(p.bbox.y + p.bbox.h / 2 for p in current_row) / len(current_row)
            else:
                # New row
                rows.append(current_row)
                current_row = [panel]
                current_row_y_center = panel_y_center

    if current_row:
        rows.append(current_row)

    # Sort within each row
    for row in rows:
        if layout == "manga":
            row.sort(key=lambda p: p.bbox.x, reverse=True)  # right→left
        else:
            row.sort(key=lambda p: p.bbox.x)  # left→right

    # Flatten and assign order_index
    ordered: list = []
    for row in rows:
        ordered.extend(row)

    for i, panel in enumerate(ordered):
        panel.order_index = i

    return PagePanels(layout=layout, panels=ordered)
