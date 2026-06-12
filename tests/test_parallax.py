"""Tests for the panel camera + 2.5D parallax overlay: trajectory invariants,
alpha encoding, background/overlay anchoring, and compositing."""

import json
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from comic_narrator.video.camera import camera_rect
from comic_narrator.video.ken_burns import ken_burns_frame
from comic_narrator.video.parallax import render_parallax_overlay
from comic_narrator.video.compose import compose_video

# The fixture page doubles as a "panel" image for unit tests — the camera
# code only cares that bbox coords share the image's coordinate space.
TEST_PAGE = Path(__file__).parent / "fixtures" / "test_page.jpg"
DUR = 1.5
FPS = 24
BBOX = (300, 500, 400, 500)  # speaker bbox on the 1200x1800 fixture


def _silent_wav(path: Path, seconds: float = 3.0, rate: int = 44100) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


def _probe_video(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-count_frames", str(path)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(out.stdout)


def _grab_luma(video: Path, t: float, out_dir: Path) -> np.ndarray:
    png = out_dir / f"{video.stem}_{t}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1", str(png)],
        check=True, capture_output=True,
    )
    return np.asarray(Image.open(png).convert("L"), dtype=np.float64)


# ── camera_rect invariants ──────────────────────────────────────────────

def test_camera_rect_stays_inside_image_and_keeps_aspect():
    iw, ih = 1200, 1800
    for bbox in (None, BBOX, (0, 0, 50, 60), (1100, 1700, 100, 100)):
        for n in (0, 10, 35):
            x, y, w, h = camera_rect(n, 36, iw, ih, speaker_bbox=bbox)
            assert x >= -1e-6 and y >= -1e-6
            assert x + w <= iw + 1e-6 and y + h <= ih + 1e-6
            assert abs((w / h) - 16 / 9) < 1e-6


def test_camera_punch_in_ends_on_speaker():
    iw, ih = 1200, 1800
    # Small, central speaker: the target rect fits without edge clamping
    bbox = (500, 800, 200, 220)
    x0, y0, w0, h0 = camera_rect(0, 36, iw, ih, speaker_bbox=bbox)
    x1, y1, w1, h1 = camera_rect(35, 36, iw, ih, speaker_bbox=bbox)
    # Camera eased in...
    assert w1 < w0 and h1 < h0
    # ...the speaker stays within the final frame WITH MARGIN (whole body),
    # i.e. the crop is never tighter than the padded subject.
    assert w1 >= bbox[2] and h1 >= bbox[3]
    # ...and the move is gentle: never tighter than max_zoom (1.5×).
    assert w0 / w1 <= 1.5 + 1e-6


def test_camera_large_speaker_barely_zooms():
    """A speaker already filling most of the panel must NOT trigger a hard
    push-in — the whole panel stays framed."""
    iw, ih = 1200, 1800
    big = (150, 300, 900, 1200)  # fills most of the frame
    _, _, w0, _ = camera_rect(0, 36, iw, ih, speaker_bbox=big)
    _, _, w1, _ = camera_rect(35, 36, iw, ih, speaker_bbox=big)
    assert w0 / w1 < 1.15, "large speaker should barely zoom"


def test_camera_no_speaker_gentle_zoom():
    iw, ih = 1200, 1800
    x0, y0, w0, h0 = camera_rect(0, 36, iw, ih, zoom_factor=1.05)
    x1, y1, w1, h1 = camera_rect(35, 36, iw, ih, zoom_factor=1.05)
    assert w0 / w1 == pytest.approx(1.05, abs=0.01)


# ── overlay behavior ────────────────────────────────────────────────────

def test_no_bbox_returns_none(tmp_path):
    out = render_parallax_overlay(TEST_PAGE, None, tmp_path / "p.webm", DUR)
    assert out is None


def test_degenerate_bbox_returns_none(tmp_path):
    # Entirely outside the 1200x1800 image
    out = render_parallax_overlay(TEST_PAGE, (5000, 5000, 100, 100), tmp_path / "p.webm", DUR)
    assert out is None


def test_overlay_is_vp9_and_small(tmp_path):
    out = render_parallax_overlay(TEST_PAGE, BBOX, tmp_path / "p.webm", DUR, fps=FPS)
    assert out is not None and out.exists()
    stream = _probe_video(out)["streams"][0]
    assert stream["codec_name"] == "vp9"
    # VP9 .webm is dramatically smaller than the old ProRes 4444 intermediate
    # (a 1.5s overlay was ~MBs as ProRes; VP9 alpha is tens of KB). The alpha
    # plane is verified by the compose round-trip test below — ffprobe does
    # not surface webm alpha in pix_fmt, so we don't assert on that string.
    assert out.stat().st_size < 5_000_000, "VP9 alpha overlay should be small"


def test_overlay_anchored_to_background(tmp_path):
    """With no pop (scale_up=1, shift=0) the cutout must land exactly on its
    own background pixels. Background and overlay share camera_rect, so a
    misalignment means the two renderers disagree on rounding/resampling."""
    kb = tmp_path / "kb.mp4"
    ken_burns_frame(TEST_PAGE, kb, DUR, fps=FPS, speaker_bbox=BBOX)
    plx = render_parallax_overlay(
        TEST_PAGE, BBOX, tmp_path / "p.webm", DUR, fps=FPS, scale_up=1.0, shift_px=0
    )
    wav = _silent_wav(tmp_path / "s.wav")
    out_with = tmp_path / "with.mp4"
    out_without = tmp_path / "without.mp4"
    compose_video(kb, plx, wav, out_with)
    compose_video(kb, None, wav, out_without)

    t = DUR / 2
    num_frames = round(DUR * FPS)
    n = round(t * FPS)
    iw, ih = Image.open(TEST_PAGE).size
    x, y, w, h = camera_rect(n, num_frames, iw, ih, speaker_bbox=BBOX)
    sx, sy = 1920 / w, 1080 / h
    bx, by, bw, bh = BBOX
    rx0, ry0 = int((bx - x) * sx), int((by - y) * sy)
    rx1, ry1 = int((bx + bw - x) * sx), int((by + bh - y) * sy)
    rx0, ry0 = max(rx0, 0), max(ry0, 0)
    rx1, ry1 = min(rx1, 1920), min(ry1, 1080)

    a = _grab_luma(out_with, t, tmp_path)
    b = _grab_luma(out_without, t, tmp_path)
    pad = 25  # stay clear of the feathered edge
    region_a = a[ry0 + pad:ry1 - pad, rx0 + pad:rx1 - pad]

    diffs = {}
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            region_b = b[ry0 + pad + dy:ry1 - pad + dy, rx0 + pad + dx:rx1 - pad + dx]
            diffs[(dx, dy)] = np.abs(region_a - region_b).mean()
    best = min(diffs, key=diffs.get)
    assert best == (0, 0), f"overlay misaligned: best shift {best}, diffs {diffs}"
    assert diffs[(0, 0)] < 15, f"overlay region diff too high: {diffs[(0, 0)]:.2f}"


def test_compose_with_overlay_changes_output(tmp_path):
    """With the real pop params the speaker region must visibly differ from
    the plain background — proves the alpha intermediate decodes and
    composites through compose_video's overlay filter."""
    kb = tmp_path / "kb.mp4"
    ken_burns_frame(TEST_PAGE, kb, DUR, fps=FPS, speaker_bbox=BBOX)
    plx = render_parallax_overlay(
        TEST_PAGE, BBOX, tmp_path / "p.webm", DUR, fps=FPS, scale_up=1.08, shift_px=12
    )
    wav = _silent_wav(tmp_path / "s.wav")
    out_with = tmp_path / "with.mp4"
    out_without = tmp_path / "without.mp4"
    compose_video(kb, plx, wav, out_with)
    compose_video(kb, None, wav, out_without)

    a = _grab_luma(out_with, DUR / 2, tmp_path)
    b = _grab_luma(out_without, DUR / 2, tmp_path)
    assert np.abs(a - b).mean() > 0.5, "overlay had no effect on composed video"

    streams = _probe_video(out_with)["streams"]
    assert {s["codec_type"] for s in streams} == {"video", "audio"}


def test_render_video_end_to_end(tmp_path):
    """Full Phase 4 path: render_video crops the panel from the page and the
    camera punches in toward the panel-relative speaker bbox."""
    from comic_narrator.render_video import render_video
    from comic_narrator.schemas import (
        BBox, Character, PageAnalysis, PagePanels, Panel, PanelAnalysis,
        Timing, TimingEntry,
    )

    page_analysis = PageAnalysis(
        layout="manga",
        panels_layout=PagePanels(layout="manga", panels=[
            Panel(id=1, bbox=BBox(x=100, y=200, w=1000, h=800), order_index=0),
        ]),
        panels_analysis=[
            PanelAnalysis(panel_id=1, characters=[
                Character(label="hero", is_speaking=True, is_visible=True,
                          bbox=BBox(x=300, y=300, w=300, h=400)),
            ]),
        ],
    )
    timing = Timing(entries=[TimingEntry(panel_id=1, start_sec=0.0, end_sec=DUR)],
                    total_duration_sec=DUR)
    wav = _silent_wav(tmp_path / "narration.wav")
    out = tmp_path / "page.mp4"
    result = render_video(TEST_PAGE, page_analysis, timing, wav, out)
    assert result == out and out.exists()
    streams = _probe_video(out)["streams"]
    assert {s["codec_type"] for s in streams} == {"video", "audio"}
    vid = next(s for s in streams if s["codec_type"] == "video")
    assert int(vid["nb_read_frames"]) >= round(DUR * FPS) - 1
