"""Ken Burns pan/zoom effect — animated crop within a panel image."""

from __future__ import annotations
from pathlib import Path


def ken_burns_frame(
    img_path: Path,
    output_path: Path,
    duration_sec: float,
    fps: int = 24,
    zoom_factor: float = 1.05,
    pan_fraction: float = 0.05,
    width: int = 1920,
    height: int = 1080,
):
    """Render a Ken Burns pan/zoom video for one panel via ffmpeg.

    Smooth zoom-in from 1.0x to zoom_factor over duration_sec,
    with subtle horizontal pan (left→right on first half, right→left on second).
    Output: H.264 MP4 at specified resolution.
    """
    import subprocess

    # ffmpeg zoompan filter
    # zoom from 1.0 to zoom_factor, pan x from 0 to pan_fraction*w
    filter_str = (
        f"zoompan=z='min(zoom+0.0005,{zoom_factor})':"
        f"x='iw/2-(iw/zoom/2)+sin(time*0.5)*{pan_fraction}*iw':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={int(duration_sec*fps)}:"
        f"s={width}x{height}:fps={fps},"
        f"format=yuv420p"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(img_path),
        "-filter_complex", filter_str,
        "-t", str(duration_sec),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
