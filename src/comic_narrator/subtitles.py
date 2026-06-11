"""SRT subtitle emission from the mix's per-event timings (Track C3).

The mixer records an EventTiming (absolute start/end + text) for every
audible event; captions and dialogue become subtitle entries. Soft subs by
default — players toggle them; burn-in is an ffmpeg one-liner left to the
caller.
"""

from __future__ import annotations

import json
from pathlib import Path

SUBTITLE_KINDS = ("dialogue", "caption")


def _fmt_ts(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    ms = round(sec * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(timing, srt_path: Path, offset_sec: float = 0.0) -> Path:
    """Write an .srt from a Timing object (or parsed timing.json dict)."""
    events = timing.get("events", []) if isinstance(timing, dict) else [
        e.model_dump() for e in timing.events
    ]
    blocks: list[str] = []
    idx = 0
    for e in events:
        if e.get("kind") not in SUBTITLE_KINDS or not e.get("text"):
            continue
        idx += 1
        blocks.append(
            f"{idx}\n"
            f"{_fmt_ts(e['start_sec'] + offset_sec)} --> "
            f"{_fmt_ts(e['end_sec'] + offset_sec)}\n"
            f"{e['text']}\n"
        )
    srt_path = Path(srt_path)
    srt_path.write_text("\n".join(blocks), encoding="utf-8")
    return srt_path


def write_book_srt(
    page_timing_jsons: list[Path],
    page_durations_sec: list[float],
    srt_path: Path,
) -> Path:
    """Merge per-page timings into one chapter .srt with cumulative offsets.

    page_durations_sec are the *video* durations of the page MP4s (ffprobe),
    which include inter-panel pauses — the authoritative offsets.
    """
    blocks: list[str] = []
    idx = 0
    offset = 0.0
    for timing_json, dur in zip(page_timing_jsons, page_durations_sec):
        if Path(timing_json).exists():
            timing = json.loads(Path(timing_json).read_text())
            for e in timing.get("events", []):
                if e.get("kind") not in SUBTITLE_KINDS or not e.get("text"):
                    continue
                idx += 1
                blocks.append(
                    f"{idx}\n"
                    f"{_fmt_ts(e['start_sec'] + offset)} --> "
                    f"{_fmt_ts(e['end_sec'] + offset)}\n"
                    f"{e['text']}\n"
                )
        offset += dur
    srt_path = Path(srt_path)
    srt_path.write_text("\n".join(blocks), encoding="utf-8")
    return srt_path


def video_duration(path: Path) -> float:
    import subprocess
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0
