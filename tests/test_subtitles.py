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


def test_normalize_tts_text():
    from comic_narrator.render_audio import normalize_tts_text
    # ALL-CAPS lettering becomes speakable sentence case
    assert normalize_tts_text("HEY, LUFFY! WHAT'RE YOU UP TO NOW?!") == \
        "Hey, luffy! what're you up to now?!"
    # Interjections map to pronounceable forms, not spelled-out letters
    assert normalize_tts_text("HMPH!") == "Humph!"
    assert normalize_tts_text("TCH... fine.") == "Tsk... fine."
    # Mixed-case text passes through untouched
    assert normalize_tts_text("One Piece") == "One Piece"


def test_lang_aware_voice_matching():
    from comic_narrator.audio.voice_bank import match_voice
    from comic_narrator.schemas import VoiceProfile
    bank = {
        "male_young_bright": VoiceProfile(voice_id="male_young_bright", gender="male",
                                          age_approx="young", pitch_category="high",
                                          timbre_tags=["bright"], voice_type="human"),
        "ja_m_twenties_x": VoiceProfile(voice_id="ja_m_twenties_x", gender="male",
                                        age_approx="young", pitch_category="medium",
                                        timbre_tags=[], voice_type="human"),
        "ja_f_fourties_y": VoiceProfile(voice_id="ja_f_fourties_y", gender="female",
                                        age_approx="adult", pitch_category="medium",
                                        timbre_tags=[], voice_type="human"),
    }
    # Japanese page: young male attrs land on the ja male, not the en archetype
    assert match_voice(["male", "young"], "human", bank, lang="ja") == "ja_m_twenties_x"
    assert match_voice(["female", "adult"], "human", bank, lang="ja") == "ja_f_fourties_y"
    # English page: legacy rules still pick the en archetype
    assert match_voice(["male", "young"], "human", bank, lang="en") == "male_young_bright"


def test_en_cast_diversity_on_collision():
    from comic_narrator.audio.voice_bank import match_voice
    from comic_narrator.schemas import VoiceProfile
    def vp(vid, **kw):
        base = dict(gender="male", age_approx="adult", pitch_category="low",
                    timbre_tags=["gruff"], voice_type="human")
        base.update(kw)
        return VoiceProfile(voice_id=vid, **base)
    bank = {
        "male_adult_gruff": vp("male_adult_gruff"),
        "male_adult_warm": vp("male_adult_warm", timbre_tags=["warm"]),
    }
    # Second gruff male: rules pick male_adult_gruff, but it's taken →
    # the best free English profile wins instead
    got = match_voice(["male", "adult"], "human", bank,
                      lang="en", exclude={"male_adult_gruff"})
    assert got == "male_adult_warm"


def test_role_based_casting():
    from comic_narrator.build_script import cast_voice
    from comic_narrator.config import PROTAGONIST_VOICE, BACKGROUND_VOICES
    # Protagonist gets the fixed lead voice
    assert cast_voice("protagonist", "male", ["male","young"], "human", None, "en", set()) == PROTAGONIST_VOICE
    # Background characters SHARE a generic voice (don't consume distinct slots)
    bg1 = cast_voice("background", "male", ["male"], "human", None, "en", {"x"})
    bg2 = cast_voice("background", "male", ["male"], "human", None, "en", {"y","z"})
    assert bg1 == bg2 == BACKGROUND_VOICES["male"]
    # A background female shares the female background voice, not a male one
    assert cast_voice("background", "female", ["female"], "human", None, "en", set()) == BACKGROUND_VOICES["female"]
    # Supporting leads never get handed a background voice
    sup = cast_voice("supporting", "male", ["male","adult"], "human", None, "en", set())
    assert sup not in BACKGROUND_VOICES.values()
