"""Ken Burns background renderer — panel-space crop driven by camera.py."""

from __future__ import annotations

import subprocess
from pathlib import Path

from comic_narrator.video.camera import camera_rect


def ken_burns_frame(
    img_path: Path,
    output_path: Path,
    duration_sec: float,
    fps: int = 24,
    zoom_factor: float = 1.05,
    pan_fraction: float = 0.05,
    width: int = 1920,
    height: int = 1080,
    speaker_bbox: tuple[int, int, int, int] | None = None,
    pacing_hint: str = "",
):
    """Render the animated background for one panel.

    img_path is the PANEL image (cropped by render_video); speaker_bbox is in
    panel coords. With a speaker the camera punches in toward them; without,
    a gentle Ken Burns drift. Frames are composed with PIL and piped raw to
    ffmpeg — the same camera_rect drives the parallax overlay, so background
    and overlay are pixel-locked by construction.
    """
    from PIL import Image

    img = Image.open(img_path).convert("RGB")
    iw, ih = img.size
    num_frames = max(1, round(duration_sec * fps))

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",
        "-frames:v", str(num_frames),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        for n in range(num_frames):
            x, y, w, h = camera_rect(
                n, num_frames, iw, ih,
                speaker_bbox=speaker_bbox,
                zoom_factor=zoom_factor,
                pan_fraction=pan_fraction,
                pacing_hint=pacing_hint,
            )
            frame = img.crop(
                (round(x), round(y), round(x + w), round(y + h))
            ).resize((width, height), Image.LANCZOS)
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        stderr = proc.stderr.read()
        proc.wait()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=stderr)
