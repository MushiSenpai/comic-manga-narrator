"""Audio mixer: pydub-based assembly of dialogue + SFX + ambient into narration.wav."""

from __future__ import annotations

from pathlib import Path
from pydub import AudioSegment

from comic_narrator.config import MIX_LEVELS, PACING
from comic_narrator.schemas import EventTiming, Timing, TimingEntry

# Breathing room appended after each event, by kind. Wall-to-wall dialogue
# reads as rushed — these gaps are the difference between a slideshow and a
# narration (PACING values come from config).
BREATH_AFTER = {
    "dialogue": PACING["dialogue_breath"],
    "caption": PACING["caption_land"],
    "sfx": 0.25,
    "silence": 0.0,
}


def mix_audio(
    event_files: list[dict],
    ambient_file: Path | None,
    output_path: Path,
    inter_panel_pause: float = 0.5,
    panel_ambients: dict[int, list[Path]] | None = None,
    panel_pauses: dict[int, float] | None = None,
) -> Timing:
    """Mix per-event WAV files into a single narration.wav. Returns timing.

    Each event_file dict: {"event_id": str, "panel_id": int, "wav_path": Path,
                           "kind": str, "pause_override": float | None,
                           "text": str (optional, recorded for subtitles),
                           "gain_db": float (optional per-event gain)}

    panel_pauses maps panel_id → pause inserted AFTER that panel (from the
    script's pacing-aware pause events); inter_panel_pause is the fallback.

    Mix levels (dB): dialogue/caption 0, sfx -9, ambient bed -18,
    plus the per-event gain_db offset (tone-driven delivery).
    """
    timeline = AudioSegment.silent(duration=0)
    timing_entries: list[TimingEntry] = []
    event_timings: list[EventTiming] = []
    current_panel_id: int | None = None
    panel_start_sec = 0.0
    panel_event_ids: list[str] = []

    for ev in event_files:
        wav_path = ev.get("wav_path")
        if not wav_path or not Path(wav_path).exists():
            continue

        seg = AudioSegment.from_file(str(wav_path))

        # Apply mix level + per-event gain (tone-driven)
        kind = ev.get("kind", "dialogue")
        db = MIX_LEVELS.get(kind, 0.0) + float(ev.get("gain_db", 0.0))
        if db != 0.0:
            seg = seg + db

        # Panel transition: close the previous panel's span, insert pause
        panel_id = ev.get("panel_id", 0)
        if current_panel_id is not None and panel_id != current_panel_id:
            if panel_event_ids:
                timing_entries.append(TimingEntry(
                    panel_id=current_panel_id,
                    start_sec=panel_start_sec,
                    end_sec=len(timeline) / 1000.0,
                    event_ids=panel_event_ids,
                ))
            pause = inter_panel_pause
            if panel_pauses and current_panel_id in panel_pauses:
                pause = panel_pauses[current_panel_id]
            timeline += AudioSegment.silent(duration=int(pause * 1000))
            panel_start_sec = len(timeline) / 1000.0
            panel_event_ids = []

        current_panel_id = panel_id
        ev_start = len(timeline) / 1000.0
        timeline += seg
        event_timings.append(EventTiming(
            event_id=ev.get("event_id", ""),
            kind=kind,
            text=ev.get("text", ""),
            start_sec=ev_start,
            end_sec=len(timeline) / 1000.0,
        ))
        panel_event_ids.append(ev.get("event_id", ""))

        # Breathing room after the event
        breath = BREATH_AFTER.get(kind, 0.3)
        if breath > 0:
            timeline += AudioSegment.silent(duration=int(breath * 1000))

    # Close last panel
    if panel_event_ids and current_panel_id is not None:
        timing_entries.append(TimingEntry(
            panel_id=current_panel_id,
            start_sec=panel_start_sec,
            end_sec=len(timeline) / 1000.0,
            event_ids=panel_event_ids,
        ))

    # Ambient beds underneath. Per-panel beds (each panel gets its own
    # soundscape derived from what's visible in that panel's art) take
    # precedence; the page-wide bed is the fallback for panels without
    # their own cues, or the legacy whole-timeline behavior when no
    # per-panel beds exist at all.
    fallback_bed = (
        Path(ambient_file) if ambient_file and Path(ambient_file).exists() else None
    )
    if panel_ambients:
        for entry in timing_entries:
            beds = panel_ambients.get(entry.panel_id) or (
                [fallback_bed] if fallback_bed else []
            )
            span_ms = int((entry.end_sec - entry.start_sec) * 1000)
            if span_ms <= 600:
                continue
            for bed_path in beds:
                if not bed_path or not Path(bed_path).exists():
                    continue
                bed = AudioSegment.from_file(str(bed_path))
                bed = bed + MIX_LEVELS.get("ambient", -18.0)
                if len(bed) < span_ms:
                    bed = bed * ((span_ms // max(len(bed), 1)) + 1)
                bed = bed[:span_ms].fade_in(300).fade_out(300)
                timeline = timeline.overlay(
                    bed, position=int(entry.start_sec * 1000)
                )
    elif fallback_bed:
        ambient = AudioSegment.from_file(str(fallback_bed))
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
        events=event_timings,
        total_duration_sec=len(timeline) / 1000.0,
    )
