"""Speaker spotlight halo — indicate who is talking without moving the camera.

Review verdict on the zoom/parallax approach: "zoom works in one scene and
not the next... highlighting the person with a halo makes more sense." So
instead of cropping/scaling/shifting the speaker (which fought the static
panel and only sometimes landed), this dims the whole panel slightly and
lifts a soft radial spotlight over the speaker — a vignette that says "look
here" while the panel stays whole and legible.

The overlay is a full-frame VP9 .webm with alpha: transparent over the
speaker, a soft dark wash everywhere else, brightening in over the first
~0.5s. compose.py decodes it with -c:v libvpx-vp9 (webm alpha is dropped
without that flag — the "silently opaque" trap). The overlay is rendered in
OUTPUT space matching the whole-panel Ken Burns framing (no zoom), so it
lines up by construction. The legacy parameters (scale_up, shift_px) are
accepted and ignored for call-site compatibility.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from comic_narrator.video.camera import camera_rect

HALO_DIM = 110          # darkness of the wash outside the spotlight (0-255 alpha)
HALO_FADE_SEC = 0.5     # ramp-in time for the spotlight


def render_parallax_overlay(
    panel_img_path: Path,
    speaker_bbox: tuple[int, int, int, int] | None,
    output_path: Path,
    duration_sec: float,
    fps: int = 24,
    zoom_factor: float = 1.05,
    pan_fraction: float = 0.05,
    scale_up: float = 1.08,   # accepted for compatibility, unused
    shift_px: int = 12,       # accepted for compatibility, unused
    width: int = 1920,
    height: int = 1080,
    pacing_hint: str = "",
) -> Path | None:
    """Render a speaker-spotlight halo overlay (full-frame, alpha).

    Returns the overlay path (.webm), or None when there is no usable bbox.
    """
    from PIL import Image, ImageDraw, ImageFilter

    if speaker_bbox is None:
        return None

    panel = Image.open(panel_img_path).convert("RGB")
    iw, ih = panel.size

    bx, by, bw, bh = speaker_bbox
    x0, y0 = max(0, bx), max(0, by)
    x1, y1 = min(iw, bx + bw), min(ih, by + bh)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    bx, by, bw, bh = x0, y0, x1 - x0, y1 - y0
    cx_panel = bx + bw / 2.0
    cy_panel = by + bh / 2.0

    num_frames = max(1, round(duration_sec * fps))

    # The Ken Burns background runs with speaker_bbox=None (whole panel), so
    # the halo must use the SAME no-speaker trajectory to stay aligned.
    def panel_to_output(px, py, n):
        x, y, w, h = camera_rect(n, num_frames, iw, ih, speaker_bbox=None,
                                 zoom_factor=zoom_factor, pan_fraction=pan_fraction)
        return (px - x) * (width / w), (py - y) * (height / h), width / w

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{width}x{height}", "-r", str(fps),
        "-i", "-", "-frames:v", str(num_frames),
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
        "-b:v", "0", "-crf", "32", "-auto-alt-ref", "0",
        str(output_path),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        for n in range(num_frames):
            ocx, ocy, scale = panel_to_output(cx_panel, cy_panel, n)
            # Spotlight radius covers the speaker (whole body) plus margin.
            rad = max(bw, bh) * scale * 0.85
            t = n / max(num_frames - 1, 1)
            ramp = min(1.0, (t * duration_sec) / HALO_FADE_SEC) if HALO_FADE_SEC else 1.0
            dim = int(HALO_DIM * ramp)

            # Dark wash everywhere, then punch a soft transparent hole on the
            # speaker. The hole is a blurred white ellipse subtracted from the
            # wash's alpha → feathered spotlight.
            wash = Image.new("RGBA", (width, height), (0, 0, 0, dim))
            hole = Image.new("L", (width, height), 0)
            d = ImageDraw.Draw(hole)
            d.ellipse(
                (ocx - rad, ocy - rad * 1.15, ocx + rad, ocy + rad * 1.15),
                fill=255,
            )
            hole = hole.filter(ImageFilter.GaussianBlur(rad * 0.35))
            wash_a = wash.split()[3]
            # subtract the hole from the wash alpha
            from PIL import ImageChops
            new_a = ImageChops.subtract(wash_a, hole)
            wash.putalpha(new_a)

            try:
                proc.stdin.write(wash.tobytes())
            except BrokenPipeError:
                break
    finally:
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        stderr = proc.stderr.read()
        proc.wait()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=stderr)

    return output_path
