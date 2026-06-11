"""Tests for SRT emission (Track C3) and the pacing-aware mixer timings."""

import wave
from pathlib import Path

from comic_narrator.audio.mixer import mix_audio, BREATH_AFTER
from comic_narrator.subtitles import write_srt, _fmt_ts


def _tone_wav(path: Path, seconds: float = 1.0, rate: int = 22050) -> Path:
    import math
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            v = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
            frames += v.to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))
    return path


def test_fmt_ts():
    assert _fmt_ts(0.0) == "00:00:00,000"
    assert _fmt_ts(61.5) == "00:01:01,500"
    assert _fmt_ts(3725.042) == "01:02:05,042"


def test_mixer_breaths_and_event_timings(tmp_path):
    """Events must not butt-join: a breath follows each by kind, and the
    mixer records absolute per-event spans for subtitles."""
    w1 = _tone_wav(tmp_path / "a.wav", 1.0)
    w2 = _tone_wav(tmp_path / "b.wav", 1.0)
    events = [
        {"event_id": "cap_1", "panel_id": 1, "wav_path": w1, "kind": "caption",
         "text": "A SMALL HARBOR VILLAGE", "pause_override": None},
        {"event_id": "dia_2", "panel_id": 1, "wav_path": w2, "kind": "dialogue",
         "text": "HEY!", "pause_override": None},
    ]
    timing = mix_audio(events, None, tmp_path / "mix.wav")

    assert len(timing.events) == 2
    cap, dia = timing.events
    # Dialogue starts only after the caption's breathing gap
    expected_gap = BREATH_AFTER["caption"]
    assert dia.start_sec - cap.end_sec >= expected_gap - 0.01
    # Total includes the trailing dialogue breath
    assert timing.total_duration_sec >= 2.0 + expected_gap + BREATH_AFTER["dialogue"] - 0.05


def test_mixer_panel_pauses(tmp_path):
    w1 = _tone_wav(tmp_path / "a.wav", 0.5)
    w2 = _tone_wav(tmp_path / "b.wav", 0.5)
    events = [
        {"event_id": "e1", "panel_id": 1, "wav_path": w1, "kind": "silence"},
        {"event_id": "e2", "panel_id": 2, "wav_path": w2, "kind": "silence"},
    ]
    timing = mix_audio(
        events, None, tmp_path / "mix.wav", panel_pauses={1: 1.2}
    )
    p1, p2 = timing.entries
    assert p2.start_sec - p1.end_sec >= 1.2 - 0.01


def test_write_srt(tmp_path):
    timing = {
        "events": [
            {"event_id": "cap_1", "kind": "caption", "text": "ONE YEAR AGO...",
             "start_sec": 0.5, "end_sec": 2.0},
            {"event_id": "sfx_1", "kind": "sfx", "text": "FWAP",
             "start_sec": 2.0, "end_sec": 2.5},  # excluded: not a subtitle kind
            {"event_id": "dia_1", "kind": "dialogue", "text": "HEY, LUFFY!",
             "start_sec": 3.0, "end_sec": 4.2},
        ]
    }
    srt = write_srt(timing, tmp_path / "out.srt")
    content = srt.read_text()
    assert "1\n00:00:00,500 --> 00:00:02,000\nONE YEAR AGO..." in content
    assert "2\n00:00:03,000 --> 00:00:04,200\nHEY, LUFFY!" in content
    assert "FWAP" not in content
