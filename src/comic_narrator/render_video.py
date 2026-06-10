"""Phase 4 orchestrator: page image + timing.json + narration.wav → output.mp4."""

from __future__ import annotations
import tempfile
from pathlib import Path

from comic_narrator.schemas import PageAnalysis, Timing
from comic_narrator.video.ken_burns import ken_burns_frame
from comic_narrator.video.parallax import render_parallax_overlay
from comic_narrator.video.compose import compose_video, concat_videos
from comic_narrator.config import (
    KEN_BURNS_ZOOM_FACTOR, KEN_BURNS_PAN_FRACTION,
    PARALLAX_SCALE, PARALLAX_SHIFT,
    VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS,
)


def render_video(
    page_image: Path,
    page_analysis: PageAnalysis,
    timing: Timing,
    narration_wav: Path,
    output_path: Path,
) -> Path:
    """Render a single page to MP4. Returns output path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Render each panel as Ken Burns clip
        panel_clips: list[Path] = []
        for entry in timing.entries:
            panel_id = entry.panel_id
            duration = entry.end_sec - entry.start_sec

            # Find matching panel analysis for speaker bbox
            speaker_bbox = None
            for pa in page_analysis.panels_analysis:
                if pa.panel_id == panel_id:
                    for char in pa.characters:
                        if char.is_speaking and char.is_visible and char.bbox:
                            speaker_bbox = (char.bbox.x, char.bbox.y, char.bbox.w, char.bbox.h)
                            break
                    break

            # Vision bboxes are panel-relative; the Ken Burns framing (and
            # therefore the parallax overlay) works in page space.
            if speaker_bbox is not None:
                panel = next(
                    (p for p in page_analysis.panels_layout.panels if p.id == panel_id),
                    None,
                )
                if panel is None:
                    speaker_bbox = None
                else:
                    speaker_bbox = (
                        panel.bbox.x + speaker_bbox[0],
                        panel.bbox.y + speaker_bbox[1],
                        speaker_bbox[2],
                        speaker_bbox[3],
                    )

            kb_out = tmp / f"kenburns_p{panel_id}.mp4"
            ken_burns_frame(
                page_image, kb_out, duration,
                zoom_factor=KEN_BURNS_ZOOM_FACTOR,
                pan_fraction=KEN_BURNS_PAN_FRACTION,
                width=VIDEO_WIDTH, height=VIDEO_HEIGHT, fps=VIDEO_FPS,
            )

            # Parallax overlay (None when the panel has no usable speaker bbox).
            # Zoom/pan must match the Ken Burns call above so the overlay
            # stays anchored to the moving background.
            plx_out = render_parallax_overlay(
                page_image, speaker_bbox, tmp / f"parallax_p{panel_id}.mov", duration,
                zoom_factor=KEN_BURNS_ZOOM_FACTOR,
                pan_fraction=KEN_BURNS_PAN_FRACTION,
                scale_up=PARALLAX_SCALE, shift_px=PARALLAX_SHIFT,
                width=VIDEO_WIDTH, height=VIDEO_HEIGHT, fps=VIDEO_FPS,
            )

            if plx_out:
                print(f"  Panel {panel_id}: parallax overlay applied")

            # Composite panel with its slice of the narration mix
            panel_out = tmp / f"panel_p{panel_id}.mp4"
            compose_video(
                kb_out, plx_out, narration_wav, panel_out,
                audio_offset_sec=entry.start_sec,
            )
            panel_clips.append(panel_out)

        # Concatenate all panels
        if len(panel_clips) == 1:
            import shutil
            shutil.copy(panel_clips[0], output_path)
        else:
            concat_videos(panel_clips, output_path)

    return output_path
