"""Phase 4 orchestrator: page image + timing.json + narration.wav → output.mp4."""

from __future__ import annotations
import tempfile
from pathlib import Path

from comic_narrator.schemas import PageAnalysis, Timing
from comic_narrator.video.ken_burns import ken_burns_frame, render_page_overview
from comic_narrator.video.parallax import render_parallax_overlay
from comic_narrator.video.compose import compose_video, concat_videos
from comic_narrator.config import (
    KEN_BURNS_ZOOM_FACTOR, KEN_BURNS_PAN_FRACTION,
    PARALLAX_SCALE, PARALLAX_SHIFT,
    VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS, PAGE_OVERVIEW_SEC,
)


def render_video(
    page_image: Path,
    page_analysis: PageAnalysis,
    timing: Timing,
    narration_wav: Path,
    output_path: Path,
) -> Path:
    """Render a single page to MP4. Returns output path.

    A1 camera language: every clip frames its PANEL (cropped from the page),
    not the whole page; panels with a speaking character get the punch-in
    (camera eases toward the speaker — A2). Vision bboxes are panel-relative,
    which is exactly the space the camera works in — no mapping needed.
    """
    from PIL import Image

    page = Image.open(page_image).convert("RGB")

    # Scratch lives next to the OUTPUT, not /tmp. Video intermediates are
    # gigabytes (a 17s ProRes 4444 alpha overlay alone is ~3GB), and /tmp is
    # often a small tmpfs — a long webtoon panel silently exhausts it and
    # ffmpeg dies mid-pipe (surfaced only as a bare BrokenPipeError).
    out_parent = Path(output_path).resolve().parent
    out_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out_parent) as tmpdir:
        tmp = Path(tmpdir)

        panel_clips: list[Path] = []

        # Establishing shot: show the whole page before going panel by panel
        if PAGE_OVERVIEW_SEC > 0 and timing.entries:
            overview = tmp / "overview.mp4"
            render_page_overview(
                page_image, overview, PAGE_OVERVIEW_SEC,
                fps=VIDEO_FPS, width=VIDEO_WIDTH, height=VIDEO_HEIGHT,
            )
            panel_clips.append(overview)

        for entry in timing.entries:
            panel_id = entry.panel_id
            duration = entry.end_sec - entry.start_sec

            # Find matching panel analysis for speaker bbox (panel coords)
            # and the panel's pacing hint (drives the A4 camera profile)
            speaker_bbox = None
            pacing_hint = ""
            for pa in page_analysis.panels_analysis:
                if pa.panel_id == panel_id:
                    pacing_hint = pa.pacing_hint
                    for char in pa.characters:
                        if char.is_speaking and char.is_visible and char.bbox:
                            speaker_bbox = (char.bbox.x, char.bbox.y, char.bbox.w, char.bbox.h)
                            break
                    break

            # Crop the panel from the page (fall back to the full page if the
            # panel isn't in the layout — degraded vision runs).
            panel = next(
                (p for p in page_analysis.panels_layout.panels if p.id == panel_id),
                None,
            )
            panel_img_path = tmp / f"panel_img_{panel_id}.png"
            if panel is not None:
                b = panel.bbox
                page.crop((b.x, b.y, b.x + b.w, b.y + b.h)).save(panel_img_path)
            else:
                page.save(panel_img_path)
                speaker_bbox = None

            kb_out = tmp / f"kenburns_p{panel_id}.mp4"
            ken_burns_frame(
                panel_img_path, kb_out, duration,
                zoom_factor=KEN_BURNS_ZOOM_FACTOR,
                pan_fraction=KEN_BURNS_PAN_FRACTION,
                width=VIDEO_WIDTH, height=VIDEO_HEIGHT, fps=VIDEO_FPS,
                speaker_bbox=speaker_bbox,
                pacing_hint=pacing_hint,
            )

            # Parallax overlay (None when the panel has no usable speaker
            # bbox). Shares camera_rect with ken_burns_frame — anchored by
            # construction.
            plx_out = render_parallax_overlay(
                panel_img_path, speaker_bbox, tmp / f"parallax_p{panel_id}.mov", duration,
                zoom_factor=KEN_BURNS_ZOOM_FACTOR,
                pan_fraction=KEN_BURNS_PAN_FRACTION,
                scale_up=PARALLAX_SCALE, shift_px=PARALLAX_SHIFT,
                width=VIDEO_WIDTH, height=VIDEO_HEIGHT, fps=VIDEO_FPS,
                pacing_hint=pacing_hint,
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
