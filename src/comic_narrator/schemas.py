"""Pydantic models for all pipeline artifacts: page.json, script.json, cast.json, timing.json."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Phase 1: Vision ────────────────────────────────────────────────────

class BBox(BaseModel):
    """Bounding box [x, y, width, height] in pixels, origin top-left."""
    x: int
    y: int
    w: int
    h: int


class Panel(BaseModel):
    """A detected panel with reading-order position."""
    id: int
    bbox: BBox
    order_index: int


class PagePanels(BaseModel):
    """Pass 1 output: panel layout of the full page."""
    schema_version: str = "1.0"
    layout: str  # "manga" | "western"
    panels: list[Panel]


class Character(BaseModel):
    """A character detected in a panel."""
    label: str
    expression: str = ""
    dominant_emotion: str = ""
    voice_attributes: list[str] = Field(default_factory=list)  # e.g. ["male","young","loud"]
    voice_type: str = "human"  # "human" | "narrator" | "monster" | "object"
    is_speaking: bool = False
    is_visible: bool = True
    bbox: Optional[BBox] = None  # speaker bounding box for parallax


class Dialogue(BaseModel):
    """A dialogue line in a panel."""
    speaker: str  # matches Character.label
    text: str
    tone: str = "neutral"  # "shouting" | "whispering" | "dismissive" | ...


class PanelAnalysis(BaseModel):
    """Pass 2 output: semantic extraction for one panel."""
    panel_id: int
    scene_description: str = ""
    characters: list[Character] = Field(default_factory=list)
    dialogues: list[Dialogue] = Field(default_factory=list)
    captions: list[str] = Field(default_factory=list)
    sfx_text: list[str] = Field(default_factory=list)
    ambient_cues: list[str] = Field(default_factory=list)
    pacing_hint: str = ""  # "dramatic_reveal" | "quick_transition" | ...


class PageAnalysis(BaseModel):
    """Full page analysis: panels layout + per-panel semantic extraction."""
    schema_version: str = "1.0"
    layout: str
    panels_layout: PagePanels
    panels_analysis: list[PanelAnalysis]


# ── Phase 2: Script ─────────────────────────────────────────────────────

class EventKind(str, Enum):
    caption = "caption"
    dialogue = "dialogue"
    sfx = "sfx"
    ambient = "ambient"
    pause = "pause"


class ScriptEvent(BaseModel):
    """A single timed event in the script."""
    event_id: str
    panel_id: int
    kind: EventKind
    text: str = ""                # dialogue/caption text; sfx cue name
    tone: str = ""                # delivery style from Pass 2 (shouting, whispering, ...)
    speaker_label: str = ""       # which character speaks
    voice_id: str = ""            # resolved voice bank ID
    duration_sec: float = 0.0      # estimated duration
    overlap: bool = False         # overlapped with next event? (v1: sequence only)
    pause_override: Optional[float] = None  # custom pause after this event


class Script(BaseModel):
    """Phase 2 output: ordered events with timing."""
    schema_version: str = "1.0"
    events: list[ScriptEvent]
    total_duration_sec: float = 0.0


class VoiceProfile(BaseModel):
    """Voice bank entry."""
    voice_id: str
    gender: str = "neutral"
    age_approx: str = "adult"
    pitch_category: str = "medium"
    timbre_tags: list[str] = Field(default_factory=list)
    voice_type: str = "human"
    reference_audio: str = ""  # path relative to voice bank dir


class CastMember(BaseModel):
    """A resolved character with locked voice assignment."""
    character_id: str
    canonical_name: str = ""
    voice_id: str
    voice_attributes: list[str] = Field(default_factory=list)
    voice_type: str = "human"
    appears_in_panels: list[int] = Field(default_factory=list)


class Cast(BaseModel):
    """Pass 3 / Phase 2 output: resolved cast with voice assignments."""
    schema_version: str = "1.0"
    narrator_voice_id: str = "_narrator"
    members: list[CastMember] = Field(default_factory=list)


# ── Phase 3: Audio ──────────────────────────────────────────────────────

class EventTiming(BaseModel):
    """Absolute span of one audible event in the final mix (drives .srt)."""
    event_id: str
    kind: str = ""
    text: str = ""
    start_sec: float
    end_sec: float


class TimingEntry(BaseModel):
    """Timing for one panel's audio block."""
    panel_id: int
    start_sec: float
    end_sec: float
    event_ids: list[str] = Field(default_factory=list)


class Timing(BaseModel):
    """Phase 3 output: exact audio timestamps."""
    schema_version: str = "1.0"
    entries: list[TimingEntry]
    events: list[EventTiming] = Field(default_factory=list)
    total_duration_sec: float = 0.0


# ── Phase 7: Book Progress ──────────────────────────────────────────────

class BookProgress(BaseModel):
    """Checkpoint file for book-scale processing."""
    pdf_path: str
    total_pages: int
    current_wave: str = "vision"  # "vision" | "audio" | "video" | "concat" | "done"
    pages_completed: list[int] = Field(default_factory=list)
    failed_pages: dict[int, str] = Field(default_factory=dict)
    cast_path: Optional[str] = None
    started_at: str = ""
    updated_at: str = ""
