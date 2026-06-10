"""2.5D parallax speaker pop — scale + shift speaker region over background.

The speaker bbox must be in page coordinates (same space as the Ken Burns
input image); render_video.py maps panel-relative vision bboxes via
panels_layout before calling in here.

The overlay replicates the exact zoompan trajectory of ken_burns.py frame by
frame, so the speaker cutout stays anchored to its page location while the
background pans/zooms underneath. The intermediate is encoded as ProRes 4444
(yuva444p10le, .mov): ffmpeg's native ProRes decoder carries alpha without
extra input flags, unlike VP9 alpha which needs -c:v libvpx-vp9 on decode
(and unlike libx264, which cannot encode an alpha plane at all).
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path


def _ken_burns_state(
    n: int, fps: int, iw: int, ih: int, zoom_factor: float, pan_fraction: float
) -> tuple[int, int, int, int]:
    """Crop rect (w, h, x, y) of ken_burns.py's zoompan at output frame n.

    Mirrors zoompan semantics, verified against rendered frames by matching
    simulated crops (residual at codec-noise level for every sampled frame):
    zoom increments 0.0005 per output frame and frame 0 already sits at
    1.0005 (the z expression sees the previous frame's zoom); time = n/fps;
    crop dimensions are floor(in/zoom); x/y are clamped against the integer
    crop size, floored, then snapped down to even values (zoompan aligns
    offsets to the 4:2:0 chroma grid of the decoded page image — skipping
    that alignment leaves the overlay up to ~2 page px off its anchor).
    """
    z = min(1.0 + 0.0005 * (n + 1), zoom_factor)
    t = n / fps
    crop_w = int(iw / z)
    crop_h = int(ih / z)
    x = iw / 2 - (iw / z) / 2 + math.sin(t * 0.5) * pan_fraction * iw
    y = ih / 2 - (ih / z) / 2
    x = int(max(0.0, min(x, iw - crop_w))) & ~1
    y = int(max(0.0, min(y, ih - crop_h))) & ~1
    return crop_w, crop_h, x, y


def render_parallax_overlay(
    page_img_path: Path,
    speaker_bbox: tuple[int, int, int, int] | None,
    output_path: Path,
    duration_sec: float,
    fps: int = 24,
    zoom_factor: float = 1.05,
    pan_fraction: float = 0.05,
    scale_up: float = 1.08,
    shift_px: int = 12,
    width: int = 1920,
    height: int = 1080,
) -> Path | None:
    """Render the speaker cutout as a transparent overlay video.

    speaker_bbox is (x, y, w, h) in page pixels. zoom_factor/pan_fraction must
    match the values given to ken_burns_frame for the same panel, otherwise
    the overlay drifts off its background anchor. Returns None (no overlay)
    when there is no usable speaker bbox.
    """
    from PIL import Image, ImageDraw, ImageFilter

    if speaker_bbox is None:
        return None

    page = Image.open(page_img_path).convert("RGB")
    iw, ih = page.size

    # Clamp bbox to the page; vision bboxes occasionally overflow panel edges.
    bx, by, bw, bh = speaker_bbox
    x0, y0 = max(0, bx), max(0, by)
    x1, y1 = min(iw, bx + bw), min(ih, by + bh)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    bx, by, bw, bh = x0, y0, x1 - x0, y1 - y0

    cutout = page.crop((bx, by, bx + bw, by + bh)).convert("RGBA")

    # Feathered alpha so the cutout reads as a layer, not a hard sticker.
    feather = max(2, min(bw, bh) // 24)
    mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(mask).rectangle(
        (feather, feather, bw - 1 - feather, bh - 1 - feather), fill=255
    )
    cutout.putalpha(mask.filter(ImageFilter.GaussianBlur(feather)))

    num_frames = max(1, round(duration_sec * fps))
    cx_page = bx + bw / 2
    cy_page = by + bh / 2

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgba",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",
        "-frames:v", str(num_frames),
        "-c:v", "prores_ks",
        "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le",
        str(output_path),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        for n in range(num_frames):
            crop_w, crop_h, kx, ky = _ken_burns_state(
                n, fps, iw, ih, zoom_factor, pan_fraction
            )
            sx = width / crop_w
            sy = height / crop_h

            # Speaker center in output space, tracking the Ken Burns crop,
            # plus the parallax drift: the foreground leads the background
            # pan (crop moving right pushes content left, so negate).
            ocx = (cx_page - kx) * sx - math.sin((n / fps) * 0.5) * shift_px
            ocy = (cy_page - ky) * sy

            layer_w = max(1, round(bw * sx * scale_up))
            layer_h = max(1, round(bh * sy * scale_up))
            layer = cutout.resize((layer_w, layer_h), Image.LANCZOS)

            frame = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            frame.paste(
                layer,
                (round(ocx - layer_w / 2), round(ocy - layer_h / 2)),
                layer,
            )
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        stderr = proc.stderr.read()
        proc.wait()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=stderr)

    return output_path
