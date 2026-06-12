"""ffmpeg video composition: Ken Burns background + parallax overlay + narration audio."""

from __future__ import annotations
from pathlib import Path


def compose_video(
    ken_burns_mp4: Path,
    parallax_overlay: Path | None,
    narration_wav: Path,
    output_path: Path,
    audio_offset_sec: float = 0.0,
):
    """Composite Ken Burns background with parallax speaker overlay and audio.

    parallax_overlay is an alpha-carrying intermediate (VP9 .webm,
    yuva420p); pass None to skip the overlay. audio_offset_sec seeks into the
    narration so each panel clip carries its own slice of the mix — without
    it, every concatenated panel restarts the narration from 0:00.
    """
    import subprocess

    audio_in = ["-ss", f"{audio_offset_sec:.3f}", "-i", str(narration_wav)]

    if parallax_overlay and parallax_overlay.exists():
        # VP9 alpha must be decoded with libvpx-vp9 explicitly, or the alpha
        # plane is silently dropped and the overlay renders opaque.
        overlay_in = (
            ["-c:v", "libvpx-vp9", "-i", str(parallax_overlay)]
            if str(parallax_overlay).endswith(".webm")
            else ["-i", str(parallax_overlay)]
        )
        # Overlay parallax on Ken Burns
        cmd = [
            "ffmpeg", "-y",
            "-i", str(ken_burns_mp4),
            *overlay_in,
            *audio_in,
            "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[outv]",
            "-map", "[outv]",
            "-map", "2:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_path),
        ]
    else:
        # No parallax — just Ken Burns + audio
        cmd = [
            "ffmpeg", "-y",
            "-i", str(ken_burns_mp4),
            *audio_in,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_path),
        ]

    subprocess.run(cmd, check=True, capture_output=True)


def concat_videos(video_paths: list[Path], output_path: Path):
    """Lossless concatenation via ffmpeg concat demuxer."""
    import subprocess

    # Write file list
    list_path = output_path.parent / "concat_list.txt"
    list_path.write_text("\n".join(f"file '{p}'" for p in video_paths))

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_path),
        "-c", "copy",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
