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
            try:
                proc.stdin.write(frame.tobytes())
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


def render_page_overview(
    img_path: Path,
    output_path: Path,
    duration_sec: float,
    fps: int = 24,
    width: int = 1920,
    height: int = 1080,
):
    """Establishing shot: the WHOLE page fit to frame (pillarboxed on black)
    with a slow push-in, before the camera goes panel by panel. Carries a
    silent mono AAC track so concat sees uniform streams."""
    from PIL import Image

    page = Image.open(img_path).convert("RGB")
    pw, ph = page.size
    fit = min(width / pw, height / ph)
    num_frames = max(1, round(duration_sec * fps))

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-frames:v", str(num_frames),
        "-shortest",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        for n in range(num_frames):
            t = n / max(num_frames - 1, 1)
            zoom = 1.0 + 0.04 * t  # slow push
            sw, sh = round(pw * fit * zoom), round(ph * fit * zoom)
            scaled = page.resize((sw, sh), Image.LANCZOS)
            frame = Image.new("RGB", (width, height), (0, 0, 0))
            frame.paste(scaled, ((width - sw) // 2, (height - sh) // 2))
            try:
                proc.stdin.write(frame.tobytes())
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
