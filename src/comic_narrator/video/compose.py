"""ffmpeg video composition: Ken Burns background + parallax overlay + narration audio."""

from __future__ import annotations
from pathlib import Path


def compose_video(
    ken_burns_mp4: Path,
    parallax_overlay: Path | None,
    narration_wav: Path | None,
    output_path: Path,
    audio_offset_sec: float = 0.0,
    video_only: bool = False,
):
    """Composite Ken Burns background with parallax speaker overlay and audio.

    parallax_overlay is an alpha-carrying intermediate (VP9 .webm,
    yuva420p); pass None to skip the overlay. audio_offset_sec seeks into the
    narration so each panel clip carries its own slice of the mix — without
    it, every concatenated panel restarts the narration from 0:00.
    """
    import subprocess

    if video_only:
        # Panel clips carry NO audio: the page narration is muxed ONCE over
        # the concatenated video (mux_audio_once). Slicing AAC per panel and
        # concatenating with -c copy caused boundary clicks and, with any
        # offset drift, whole spans of dead audio — verified on a real
        # render where 80% of the file went silent.
        if parallax_overlay and parallax_overlay.exists():
            overlay_in = (
                ["-c:v", "libvpx-vp9", "-i", str(parallax_overlay)]
                if str(parallax_overlay).endswith(".webm")
                else ["-i", str(parallax_overlay)]
            )
            cmd = ["ffmpeg", "-y", "-i", str(ken_burns_mp4), *overlay_in,
                   "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[outv]",
                   "-map", "[outv]",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                   "-an", str(output_path)]
        else:
            cmd = ["ffmpeg", "-y", "-i", str(ken_burns_mp4),
                   "-c:v", "copy", "-an", str(output_path)]
        subprocess.run(cmd, check=True, capture_output=True)
        return

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


def concat_videos(video_paths: list[Path], output_path: Path,
                  reencode_audio: bool = False):
    """Concatenate via ffmpeg concat demuxer (video stream copied).

    reencode_audio=True re-encodes the audio at the joins — copying
    separately-encoded AAC streams leaves priming-sample gaps that play as
    clicks/static at every boundary (use for book-level page joins).
    """
    import subprocess

    # Write file list
    list_path = output_path.parent / "concat_list.txt"
    list_path.write_text("\n".join(f"file '{p}'" for p in video_paths))

    audio_args = (["-c:a", "aac", "-b:a", "192k", "-af", "aresample=async=1"]
                  if reencode_audio else ["-c:a", "copy"])
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_path),
        "-c:v", "copy", *audio_args,
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def mux_audio_once(video_path: Path, narration_wav: Path, output_path: Path,
                   audio_delay_sec: float = 0.0):
    """Mux ONE continuous narration over an (audio-less) video.

    The narration starts after audio_delay_sec (the establishing shot) and is
    padded with silence to the video's length. Single encode, no per-clip
    slicing — sync and continuity by construction.
    """
    import subprocess
    delay_ms = int(audio_delay_sec * 1000)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(narration_wav),
        "-filter_complex", f"[1:a]adelay={delay_ms}:all=1,apad[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
