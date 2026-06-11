"""Phase 1 orchestrator: full page → page.json via 3-pass vision pipeline."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Optional

from comic_narrator.config import PANEL_DETECTION_MIN_AREA, PANEL_DETECTION_GUTTER
from comic_narrator.schemas import Cast, PageAnalysis, PagePanels
from comic_narrator.vision.panels import detect_panels, extract_panel_image
from comic_narrator.vision.reading_order import assign_reading_order
from comic_narrator.vision.nemotron_client import NemotronClient


def parse_page(
    image_path: Path,
    layout: str = "manga",
    lang: str = "en",
    voice_bank_ids: Optional[list[str]] = None,
    prior_cast: Optional[Cast] = None,
    panels_override: Optional[PagePanels] = None,
    nemotron_url: str = "http://localhost:8000/v1",
    nemotron_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    output_path: Optional[Path] = None,
) -> PageAnalysis:
    """
    Run the full 3-pass vision pipeline on a comic page.

    1. OpenCV panel detection → initial bboxes
    2. Reading-order sort by layout flag
    3. Nemotron Pass 1: refine panel layout (optional, if bboxes seem wrong)
    4. Nemotron Pass 2: per-panel semantic extraction (crop → analyze)
    5. Nemotron Pass 3: cross-panel cast consolidation

    Args:
        image_path: Path to the comic page image.
        layout: "manga" or "western".
        voice_bank_ids: Available voice IDs for cast assignment.
        prior_cast: Existing cast from previous pages (Phase 7).
        panels_override: Pre-made panels JSON (skips OpenCV + Pass 1).
        nemotron_url: vLLM endpoint.
        nemotron_model: Model name string.
        output_path: If set, write page.json here.

    Returns:
        PageAnalysis with panels_layout + panels_analysis.
    """
    client = NemotronClient(base_url=nemotron_url, model=nemotron_model)

    # ── Step 1: Panel detection ──────────────────────────────────────
    if panels_override is not None:
        panels_layout = panels_override
    else:
        panels_layout = detect_panels(
            image_path,
            min_area_frac=PANEL_DETECTION_MIN_AREA,
            gutter_thresh=PANEL_DETECTION_GUTTER,
        )

    # ── Step 2: Reading order ────────────────────────────────────────
    panels_layout = assign_reading_order(panels_layout, layout)

    # ── Step 3: Nemotron Pass 1 — refine panels (if OpenCV seems insufficient) ──
    # For v1: OpenCV is primary, Nemotron Pass 1 is called only if:
    # - panel count is 0 or 1 (likely missed panels)
    # - panels_override not provided (user trusts OpenCV)
    if not panels_override and len(panels_layout.panels) <= 1:
        try:
            panels_layout = client.pass1_detect_panels(image_path, layout)
            panels_layout = assign_reading_order(panels_layout, layout)
        except Exception:
            pass  # Keep OpenCV result

    # ── Step 4: Nemotron Pass 2 — per-panel semantic extraction ──────
    panels_analysis = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for panel in panels_layout.panels:
            # Crop panel image
            panel_img_path = extract_panel_image(image_path, panel.bbox, tmp)

            try:
                analysis = client.pass2_analyze_panel(panel_img_path, panel.id, lang=lang)
            except Exception as e:
                # Log error and create stub analysis so pipeline doesn't halt
                from comic_narrator.schemas import PanelAnalysis
                analysis = PanelAnalysis(panel_id=panel.id)
                print(f"  [WARN] Pass 2 failed for panel {panel.id}: {e}")

            panels_analysis.append(analysis)

    # ── Step 5: Nemotron Pass 3 — cast consolidation ─────────────────
    if voice_bank_ids is None:
        voice_bank_ids = [
            "_narrator", "male_young_bright", "male_adult_gruff",
            "female_young_bright", "female_adult_warm", "monster_deep",
        ]

    try:
        cast = client.pass3_consolidate_cast(
            panels_analysis, voice_bank_ids,
            narrator_voice_id="_narrator",
            prior_cast=prior_cast,
        )
    except Exception:
        cast = Cast()

    # ── Build result ─────────────────────────────────────────────────
    result = PageAnalysis(
        layout=panels_layout.layout,
        panels_layout=panels_layout,
        panels_analysis=panels_analysis,
    )

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.model_dump_json(indent=2))
        # Also write cast.json next to page.json
        cast_path = output_path.parent / "cast.json"
        cast_path.write_text(cast.model_dump_json(indent=2))

    return result
