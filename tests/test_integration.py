"""Integration smoke test for the Phase 3 → Phase 4 seam.

Bug 8 (a mangled render_audio returning None) sailed through 24 green unit
tests because nothing exercised render_audio → render_video end-to-end.
This test does, with TTS mocked at the FishSpeechTTS boundary — no gateway,
no GPU, no Freesound.
"""

import math
import wave
from pathlib import Path

import pytest

from comic_narrator.schemas import (
    BBox, Character, EventKind, PageAnalysis, PagePanels, Panel,
    PanelAnalysis, Script, ScriptEvent,
)

TEST_PAGE = Path(__file__).parent / "fixtures" / "test_page.jpg"


def _fake_synthesize(self, text, voice_id, output_path, speed=1.0, **kwargs):
    """Stand-in for the gateway: writes a 0.8s tone, returns its duration."""
    rate = 44100
    seconds = 0.8
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            v = int(9000 * math.sin(2 * math.pi * 330 * i / rate))
            frames += v.to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))
    return seconds


@pytest.fixture
def script_and_analysis():
    script = Script(events=[
        ScriptEvent(event_id="cap_001", panel_id=1, kind=EventKind.caption,
                    text="A SMALL HARBOR VILLAGE", voice_id="_narrator",
                    speaker_label="narrator", duration_sec=2.0),
        ScriptEvent(event_id="dia_002", panel_id=1, kind=EventKind.dialogue,
                    text="HMPH!", tone="dismissive", speaker_label="hero",
                    voice_id="male_young_bright", duration_sec=1.0),
        ScriptEvent(event_id="pau_003", panel_id=1, kind=EventKind.pause,
                    duration_sec=0.5, pause_override=0.5),
        ScriptEvent(event_id="dia_004", panel_id=2, kind=EventKind.dialogue,
                    text="WAIT!", tone="shouting", speaker_label="other",
                    voice_id="male_adult_gruff", duration_sec=1.0),
    ], total_duration_sec=4.5)
    analysis = PageAnalysis(
        layout="western",
        panels_layout=PagePanels(layout="western", panels=[
            Panel(id=1, bbox=BBox(x=24, y=24, w=1152, h=536), order_index=0),
            Panel(id=2, bbox=BBox(x=24, y=584, w=550, h=716), order_index=1),
        ]),
        panels_analysis=[
            PanelAnalysis(panel_id=1, characters=[
                Character(label="hero", is_speaking=True, is_visible=True,
                          bbox=BBox(x=300, y=100, w=200, h=260)),
            ]),
            PanelAnalysis(panel_id=2, pacing_hint="action_peak"),
        ],
    )
    return script, analysis


def test_render_audio_to_video_smoke(tmp_path, monkeypatch, script_and_analysis):
    """Phases 3+4 run end-to-end and produce a playable MP4 + valid timing."""
    from comic_narrator.audio.tts_fish import FishSpeechTTS
    from comic_narrator.render_audio import render_audio
    from comic_narrator.render_video import render_video

    monkeypatch.setattr(FishSpeechTTS, "synthesize", _fake_synthesize)
    monkeypatch.setattr(FishSpeechTTS, "health_check", lambda self: True)

    script, analysis = script_and_analysis
    narration, timing = render_audio(script, output_dir=tmp_path)

    assert narration.exists()
    assert timing.total_duration_sec > 0
    # Both panels covered, per-event spans recorded for subtitles
    assert {e.panel_id for e in timing.entries} == {1, 2}
    assert len([e for e in timing.events if e.kind in ("caption", "dialogue")]) == 3
    # timing.json written next to the mix
    assert (tmp_path / "timing.json").exists()

    out = tmp_path / "page.mp4"
    render_video(TEST_PAGE, analysis, timing, narration, out)
    assert out.exists() and out.stat().st_size > 50_000

    import subprocess, json
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(out)],
        check=True, capture_output=True, text=True).stdout)
    kinds = {s["codec_type"] for s in probe["streams"]}
    assert kinds == {"video", "audio"}
