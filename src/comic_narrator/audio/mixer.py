"""Audio mixer: pydub-based assembly of dialogue + SFX + ambient into narration.wav."""

from __future__ import annotations

from pathlib import Path
from pydub import AudioSegment

from comic_narrator.config import MIX_LEVELS
from comic_narrator.schemas import Timing, TimingEntry


def mix_audio(
    event_files: list[dict],
    ambient_file: Path | None,
    output_path: Path,
    inter_panel_pause: float = 0.5,
) -> Timing:
    """Mix per-event WAV files into a single narration.wav. Returns timing.

    Each event_file dict: {"event_id": str, "panel_id": int, "wav_path": Path,
                           "kind": str, "pause_override": float | None}

    Mix levels (dB):
    - dialogue/caption: 0 dB
    - sfx: -9 dB
    - ambient bed: -18 dB
    """
    timeline = AudioSegment.silent(duration=0)
    timing_entries: list[TimingEntry] = []
    current_panel_id: int | None = None
    panel_start_sec = 0.0
    panel_event_ids: list[str] = []

    for ev in event_files:
        wav_path = ev.get("wav_path")
        if not wav_path or not Path(wav_path).exists():
            continue

        seg = AudioSegment.from_file(str(wav_path))

        # Apply mix level
        kind = ev.get("kind", "dialogue")
        db = MIX_LEVELS.get(kind, 0.0)
        if db != 0.0:
            seg = seg + db

        # Inter-panel pause
        panel_id = ev.get("panel_id", 0)
        if current_panel_id is not None and panel_id != current_panel_id:
            pause = inter_panel_pause
            pause_override = ev.get("pause_override")
            if pause_override is not None:
                pause = pause_override
            # Close previous panel timing
            if panel_event_ids:
                timing_entries.append(TimingEntry(
                    panel_id=current_panel_id,
                    start_sec=panel_start_sec,
                    end_sec=len(timeline) / 1000.0,
                    event_ids=panel_event_ids,
                ))
            # Add silence
            timeline += AudioSegment.silent(duration=int(pause * 1000))
            panel_start_sec = len(timeline) / 1000.0
            panel_event_ids = []

        current_panel_id = panel_id
        timeline += seg
        panel_event_ids.append(ev.get("event_id", ""))

    # Close last panel
    if panel_event_ids and current_panel_id is not None:
        timing_entries.append(TimingEntry(
            panel_id=current_panel_id,
            start_sec=panel_start_sec,
            end_sec=len(timeline) / 1000.0,
            event_ids=panel_event_ids,
        ))

    # Mix ambient bed underneath (if provided)
    if ambient_file and Path(ambient_file).exists():
        ambient = AudioSegment.from_file(str(ambient_file))
        ambient = ambient + MIX_LEVELS.get("ambient", -18.0)
        # Loop ambient to match timeline length
        if len(ambient) < len(timeline):
            loops = (len(timeline) // len(ambient)) + 1
            ambient = ambient * loops
        ambient = ambient[:len(timeline)]
        timeline = timeline.overlay(ambient)

    # Export
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timeline.export(str(output_path), format="wav")

    return Timing(
        entries=timing_entries,
        total_duration_sec=len(timeline) / 1000.0,
    )
