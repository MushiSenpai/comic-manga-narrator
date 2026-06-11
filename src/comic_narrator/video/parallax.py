"""2.5D parallax speaker pop — scale + drift the speaker over the background.

The overlay consumes the SAME camera_rect as ken_burns.py, so it is anchored
to the moving background by construction. (v0.2 rendered the background with
ffmpeg zoompan and replicated its crop math here — including an undocumented
even-snap; owning the trajectory in camera.py removes that failure class.)

The intermediate is ProRes 4444 (yuva444p10le, .mov): ffmpeg's native ProRes
decoder carries alpha without extra input flags, unlike VP9 alpha (needs
-c:v libvpx-vp9 on decode) and libx264 (cannot encode alpha at all).

Coordinates: panel space — both the image and speaker_bbox are the panel
crop produced by render_video.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

from comic_narrator.video.camera import camera_rect


def render_parallax_overlay(
    panel_img_path: Path,
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

    Returns the overlay path (.mov), or None when there is no usable bbox —
    compose_video skips the overlay in that case.
    """
    from PIL import Image, ImageDraw, ImageFilter

    if speaker_bbox is None:
        return None

    panel = Image.open(panel_img_path).convert("RGB")
    iw, ih = panel.size

    # Clamp bbox to the panel; vision bboxes occasionally overflow edges.
    bx, by, bw, bh = speaker_bbox
    x0, y0 = max(0, bx), max(0, by)
    x1, y1 = min(iw, bx + bw), min(ih, by + bh)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    bx, by, bw, bh = x0, y0, x1 - x0, y1 - y0
    bbox = (bx, by, bw, bh)

    cutout = panel.crop((bx, by, bx + bw, by + bh)).convert("RGBA")

    # Feathered alpha so the cutout reads as a layer, not a hard sticker.
    feather = max(2, min(bw, bh) // 24)
    mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(mask).rectangle(
        (feather, feather, bw - 1 - feather, bh - 1 - feather), fill=255
    )
    cutout.putalpha(mask.filter(ImageFilter.GaussianBlur(feather)))

    num_frames = max(1, round(duration_sec * fps))
    cx_panel = bx + bw / 2.0
    cy_panel = by + bh / 2.0

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
            x, y, w, h = camera_rect(
                n, num_frames, iw, ih,
                speaker_bbox=bbox,
                zoom_factor=zoom_factor,
                pan_fraction=pan_fraction,
            )
            sx = width / w
            sy = height / h

            # Speaker center in output space, plus the parallax drift —
            # the foreground leads the camera slightly.
            ocx = (cx_panel - x) * sx - math.sin((n / fps) * 0.5) * shift_px
            ocy = (cy_panel - y) * sy

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
