"""Phase 2: PageAnalysis → script.json + cast.json.

Walks panels in reading order, emits timed events with voice assignments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from comic_narrator.audio.voice_bank import init_voice_bank, match_voice
from comic_narrator.config import (
    PACING,
    DEFAULT_NARRATOR_VOICE,
    DEFAULT_FALLBACK_VOICE,
)
from comic_narrator.schemas import (
    Cast,
    CastMember,
    EventKind,
    PageAnalysis,
    PanelAnalysis,
    Script,
    ScriptEvent,
)


def estimate_duration(text: str, kind: EventKind) -> float:
    """Estimate duration in seconds for an event.

    TTS-based estimates for dialogue/captions; fixed ranges for SFX/pauses.
    Actual durations are replaced post-TTS render in Phase 3.
    """
    if kind in (EventKind.dialogue, EventKind.caption):
        # Rough: ~150 words/min = 2.5 words/sec, avg 5 chars/word → ~12.5 chars/sec
        word_count = len(text.split())
        if word_count == 0:
            word_count = max(1, len(text) // 5)
        duration = word_count / 2.5  # seconds
        return max(1.0, duration)  # minimum 1 second
    elif kind == EventKind.sfx:
        return (PACING["sfx_min"] + PACING["sfx_max"]) / 2
    elif kind == EventKind.ambient:
        return 3.0  # ambient bed runs for panel duration, placeholder
    elif kind == EventKind.pause:
        return (PACING["inter_panel_pause_min"] + PACING["inter_panel_pause_max"]) / 2
    return 2.0


def build_script(
    page_analysis: PageAnalysis,
    narrator_voice_id: str = DEFAULT_NARRATOR_VOICE,
    voice_bank_ids: Optional[list[str]] = None,
    voice_bank_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> tuple[Script, Cast]:
    """Convert PageAnalysis into a timed script with voice assignments.

    Algorithm:
    1. Walk panels in reading order (panels_analysis sorted by panels_layout.order_index).
    2. For each panel:
       a. Emit ambient event (scene background bed).
       b. Emit caption events (narrator reads).
       c. Emit dialogue events (per character, voice-assigned).
       d. Emit SFX events (sound effect cues).
       e. Emit inter-panel pause.
    3. Build cast.json from all characters found across panels.

    Args:
        page_analysis: Output from Phase 1 (parse_page).
        narrator_voice_id: Voice ID for caption narration.
        voice_bank_ids: Available voice IDs for assignment.
        voice_bank_dir: If set, init/load the voice bank here (overrides
            voice_bank_ids and enables voice_type-aware matching).
        output_dir: If set, write script.json + cast.json here.

    Returns:
        (Script, Cast) — timed events plus character voice assignments.
    """
    voice_bank = None
    if voice_bank_dir is not None:
        voice_bank = init_voice_bank(Path(voice_bank_dir))
    if voice_bank_ids is None:
        if voice_bank:
            voice_bank_ids = list(voice_bank)
        else:
            voice_bank_ids = [
                "_narrator", "male_young_bright", "male_adult_gruff",
                "female_young_bright", "female_adult_warm", "monster_deep",
            ]

    events: list[ScriptEvent] = []
    char_map: dict[str, str] = {}  # label → voice_id
    cast_members: dict[str, CastMember] = {}
    event_counter = 0

    # Sort panels by reading order
    panels = sorted(page_analysis.panels_analysis, 
                    key=lambda p: next(
                        (pp.order_index for pp in page_analysis.panels_layout.panels 
                         if pp.id == p.panel_id), 99))

    for panel in panels:
        # ── Ambient bed ──────────────────────────────────────────────
        if panel.ambient_cues:
            event_counter += 1
            events.append(ScriptEvent(
                event_id=f"amb_{event_counter:03d}",
                panel_id=panel.panel_id,
                kind=EventKind.ambient,
                text=", ".join(panel.ambient_cues),
                duration_sec=estimate_duration("", EventKind.ambient),
            ))

        # ── Captions (narrator) ──────────────────────────────────────
        for caption in panel.captions:
            event_counter += 1
            duration = estimate_duration(caption, EventKind.caption)
            events.append(ScriptEvent(
                event_id=f"cap_{event_counter:03d}",
                panel_id=panel.panel_id,
                kind=EventKind.caption,
                text=caption,
                speaker_label="narrator",
                voice_id=narrator_voice_id,
                duration_sec=duration,
            ))

        # ── Dialogues ────────────────────────────────────────────────
        for dialogue in panel.dialogues:
            event_counter += 1
            speaker = dialogue.speaker

            # Resolve voice
            if speaker not in char_map:
                # Find character attributes from panel.characters
                attrs: list[str] = []
                voice_type = "human"
                for char in panel.characters:
                    if char.label == speaker:
                        attrs = char.voice_attributes
                        voice_type = char.voice_type
                        break
                char_map[speaker] = match_voice(attrs, voice_type, voice_bank)

            voice_id = char_map[speaker]
            duration = estimate_duration(dialogue.text, EventKind.dialogue)
            events.append(ScriptEvent(
                event_id=f"dia_{event_counter:03d}",
                panel_id=panel.panel_id,
                kind=EventKind.dialogue,
                text=dialogue.text,
                speaker_label=speaker,
                voice_id=voice_id,
                duration_sec=duration,
            ))

        # ── SFX ──────────────────────────────────────────────────────
        for sfx in panel.sfx_text:
            event_counter += 1
            duration = (PACING["sfx_min"] + PACING["sfx_max"]) / 2
            events.append(ScriptEvent(
                event_id=f"sfx_{event_counter:03d}",
                panel_id=panel.panel_id,
                kind=EventKind.sfx,
                text=sfx,
                duration_sec=duration,
            ))

        # ── Inter-panel pause ────────────────────────────────────────
        pause = PACING["inter_panel_pause_min"]
        if panel.pacing_hint == "dramatic_reveal":
            pause = PACING["inter_panel_pause_max"] * 1.5
        elif panel.pacing_hint == "quick_transition":
            pause = PACING["inter_panel_pause_min"] * 0.5

        event_counter += 1
        events.append(ScriptEvent(
            event_id=f"pau_{event_counter:03d}",
            panel_id=panel.panel_id,
            kind=EventKind.pause,
            duration_sec=pause,
            pause_override=pause,
        ))

    # ── Build Cast ───────────────────────────────────────────────────
    members: list[CastMember] = []
    for panel in panels:
        for char in panel.characters:
            if char.label not in cast_members:
                voice_id = char_map.get(char.label, DEFAULT_FALLBACK_VOICE)
                member = CastMember(
                    character_id=char.label,
                    canonical_name=char.label,
                    voice_id=voice_id,
                    voice_attributes=char.voice_attributes,
                    voice_type=char.voice_type,
                    appears_in_panels=[panel.panel_id],
                )
                cast_members[char.label] = member
                members.append(member)
            else:
                if panel.panel_id not in cast_members[char.label].appears_in_panels:
                    cast_members[char.label].appears_in_panels.append(panel.panel_id)

    total_duration = sum(e.duration_sec for e in events)
    script = Script(
        events=events,
        total_duration_sec=total_duration,
    )
    cast = Cast(
        narrator_voice_id=narrator_voice_id,
        members=members,
    )

    # Write outputs
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "script.json").write_text(script.model_dump_json(indent=2))
        (output_dir / "cast.json").write_text(cast.model_dump_json(indent=2))

    return script, cast
