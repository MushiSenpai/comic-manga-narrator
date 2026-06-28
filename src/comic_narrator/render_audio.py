"""Phase 3 orchestrator: script.json + cast.json → narration.wav + timing.json."""

from __future__ import annotations

import re
from pathlib import Path

from comic_narrator.schemas import Script, Timing
from comic_narrator.audio.tts_fish import FishSpeechTTS
from comic_narrator.audio.freesound import FreesoundClient
from comic_narrator.audio.mixer import mix_audio
from comic_narrator.config import VOICE_BANK_DIR, SFX_CACHE_DIR, SFX_MAP_PATH, PACING


# B1 — tone → (speed mult, gain dB, temperature, top_p). speed/gain shape
# pace+volume; temperature/top_p drive PROSODIC VARIATION (higher = livelier,
# less monotone — the real lever against "lifeless" delivery). The baseline
# (no tone) is bumped to 0.85/0.85 from Fish Speech's flat 0.7 default so
# even neutral lines have some life. Honest ceiling: this varies prosody, it
# does not "act" — true acting needs emotion-variant reference clips (B2).
TONE_DELIVERY = {
    "":           (1.00, 0.0,  0.85, 0.85),
    "shouting":   (1.12, 4.0,  0.98, 0.95),
    "loud":       (1.06, 3.0,  0.92, 0.92),
    "excited":    (1.10, 2.0,  0.98, 0.95),
    "angry":      (1.08, 3.0,  0.95, 0.92),
    "whispering": (0.86, -6.0, 0.70, 0.80),
    "nervous":    (1.08, 0.0,  0.90, 0.90),
    "sad":        (0.90, -2.0, 0.72, 0.82),
    "dismissive": (0.94, -1.0, 0.80, 0.85),
    "confident":  (1.00, 1.0,  0.85, 0.88),
}
TONE_DELIVERY_DEFAULT = TONE_DELIVERY[""]

# Comics lettering is ALL CAPS by convention; TTS engines read caps as
# spelled-out letters or robotic emphasis. Interjections are expressions,
# not words to spell ("HMPH" must sound like a scoff, not aitch-em-pee-aitch).
# Subtitles keep the original lettering — only the TTS input is normalized.
INTERJECTIONS = {
    "hmph": "humph",
    "hmm": "hmm",
    "hm": "hmm",
    "tch": "tsk",
    "grr": "grrr",
    "ugh": "ugh",
    "huh": "huh",
    "heh": "heh",
    "pfft": "pfft",
    "gah": "gah",
    "eh": "eh",
    "ow": "ow",
    "whew": "phew",
}

# Caption-triggered one-shot cue queries: when narration TEXT names an
# audible phenomenon ("THE WIND BLOWS FROM THE EAST"), play the sound right
# after the line — "wind blowing... woooosh".
CAPTION_CUES = {
    "wind": "wind gust",
    "waves": "wave crash",
    "rain": "rain falling",
    "thunder": "thunder clap",
    "seagull": "seagull cry",
    "seagulls": "seagull cry",
    "birds": "birds chirping",
    "crowd": "crowd murmur",
    "explosion": "explosion",
    "storm": "storm wind",
}


# B2 — tone → emotion-variant bucket. If the bank has a
# {voice_id}__{emotion}.wav reference, the same character speaks with that
# affect; otherwise the base reference is used (speed/gain still apply).
TONE_EMOTION = {
    "shouting": "angry",
    "loud": "angry",
    "whispering": "soft",
    "nervous": "nervous",
    "sad": "sad",
    "crying": "sad",
    "excited": "excited",
}


def normalize_tts_text(text: str) -> str:
    """Make comics lettering speakable: de-caps + expand interjections."""
    t = text.strip()
    if t.isupper():
        t = t.lower()
        t = t[:1].upper() + t[1:]
    words = re.split(r"(\W+)", t)
    out = []
    for w in words:
        if w.isalpha() and w.lower() in INTERJECTIONS:
            r = INTERJECTIONS[w.lower()]
            out.append(r.capitalize() if w[:1].isupper() else r)
        else:
            out.append(w)
    return "".join(out)


def render_audio(
    script: Script,
    voice_bank_dir: Path = VOICE_BANK_DIR,
    sfx_cache_dir: Path = SFX_CACHE_DIR,
    sfx_map_path: Path = SFX_MAP_PATH,
    freesound_api_key: str = "",
    output_dir: Path | None = None,
) -> tuple[Path, Timing]:
    """Render script events to audio. Returns (narration.wav path, timing)."""
    if output_dir is None:
        output_dir = Path("/tmp/comic-narrator-audio")

    output_dir.mkdir(parents=True, exist_ok=True)
    wav_dir = output_dir / "wavs"
    wav_dir.mkdir(parents=True, exist_ok=True)

    # TTS engine: two-stage expressive (Track H) when enabled + available,
    # else single-stage Fish Speech. TwoStageTTS falls back per-line anyway.
    from comic_narrator.config import TTS_ENGINE, TWO_STAGE_TTS
    engine = TTS_ENGINE if TTS_ENGINE in ("fish", "indextts2", "two_stage") else "fish"
    if TWO_STAGE_TTS and engine == "fish":
        engine = "two_stage"  # back-compat with the older flag
    if engine == "indextts2":
        from comic_narrator.audio.indextts2_tts import IndexTTS2TTS
        tts = IndexTTS2TTS()
    elif engine == "two_stage":
        from comic_narrator.audio.two_stage_tts import TwoStageTTS
        tts = TwoStageTTS(enabled=True)
    else:
        tts = FishSpeechTTS()
    # Engines other than plain Fish accept tone/gender kwargs (expressive).
    expressive = engine in ("indextts2", "two_stage")

    # Per-character gender hint (for the Stage-1 delivery brief).
    gender_by_voice = {
        m.voice_id: next((a for a in m.voice_attributes if a in ("male", "female")), "person")
        for m in getattr(getattr(script, "cast", None), "members", []) or []
    }

    tts_events = [
        {
            "event_id": e.event_id,
            "text": e.text,
            "voice_id": e.voice_id,
            "kind": e.kind.value,
            "tone": e.tone,
            "panel_id": e.panel_id,
            "pause_override": e.pause_override,
        }
        for e in script.events
        if e.kind.value in ("dialogue", "caption") and e.text
    ]

    event_files: list[dict] = []
    for ev in tts_events:
        out_wav = wav_dir / f"{ev['event_id']}.wav"
        tone = ev.get("tone", "")
        speed, gain_db, temperature, top_p = TONE_DELIVERY.get(
            tone, TONE_DELIVERY_DEFAULT)
        emotion = TONE_EMOTION.get(tone, "")
        try:
            if expressive:
                tts.synthesize(
                    normalize_tts_text(ev["text"]), ev["voice_id"], out_wav,
                    speed=speed, emotion=emotion, tone=tone,
                    gender=gender_by_voice.get(ev["voice_id"], "person"),
                    temperature=temperature, top_p=top_p)
            else:
                tts.synthesize(normalize_tts_text(ev["text"]), ev["voice_id"], out_wav,
                               speed=speed, emotion=emotion,
                               temperature=temperature, top_p=top_p)
            event_files.append({**ev, "wav_path": out_wav, "gain_db": gain_db})
        except Exception as e:
            print(f"  [WARN] TTS failed for {ev['event_id']}: {e}")

    # SFX events: drawn sound text AND visual SFX (E3 — sounds implied by
    # visible action: seagulls → cries, cow → moo) resolve via Freesound at
    # -9dB, clearly audible over the ducked ambient beds.
    if freesound_api_key:
        sfx_client = FreesoundClient(freesound_api_key, sfx_cache_dir, sfx_map_path)
        for e in script.events:
            if e.kind.value == "sfx" and e.text:
                sfx_path = sfx_client.resolve_sfx(e.text)
                if sfx_path:
                    event_files.append({
                        "event_id": e.event_id,
                        "panel_id": e.panel_id,
                        "wav_path": sfx_path,
                        "kind": "sfx",
                        "pause_override": e.pause_override,
                    })

    # Caption-triggered one-shot cues, inserted immediately after the caption
    # that names the phenomenon, a touch louder than SFX level so it reads as
    # a cue, not texture.
    if freesound_api_key:
        sfx_client = FreesoundClient(freesound_api_key, sfx_cache_dir, sfx_map_path)
        cued: list[dict] = []
        for ef in event_files:
            cued.append(ef)
            if ef.get("kind") != "caption":
                continue
            words = set(re.findall(r"[a-z']+", ef.get("text", "").lower()))
            for word, query in CAPTION_CUES.items():
                if word in words:
                    cue_path = sfx_client.resolve_sfx(query)
                    if cue_path:
                        cued.append({
                            "event_id": f"{ef['event_id']}_cue_{word}",
                            "panel_id": ef["panel_id"],
                            "wav_path": cue_path,
                            "kind": "sfx",
                            "gain_db": 3.0,
                            "pause_override": None,
                        })
                    break  # one cue per caption
        event_files = cued

    # Resolve ambient beds PER PANEL. The cues come from Pass 2 reading the
    # artwork itself (visible birds → gull cries, ship on water → waves) —
    # not from drawn sound text. This is the forensic-soundscape idea: the
    # harbor panel gets seagulls, the deck panel gets wind and creaking,
    # instead of one flattened bed across the whole page.
    ambient_file = None
    panel_ambients: dict[int, list[Path]] = {}
    if freesound_api_key:
        sfx_client = FreesoundClient(freesound_api_key, sfx_cache_dir, sfx_map_path)
        for e in script.events:
            if e.kind.value == "ambient" and e.text:
                cues = [c.strip() for c in e.text.split(",") if c.strip()]
                for cue in cues[:2]:  # layer up to 2 beds per panel
                    bed = sfx_client.resolve_ambient_bed(cue)
                    if bed:
                        panel_ambients.setdefault(e.panel_id, []).append(bed)
        # Page-wide fallback bed for panels without cues of their own
        all_cues = [
            c.strip()
            for e in script.events if e.kind.value == "ambient" and e.text
            for c in e.text.split(",") if c.strip()
        ]
        if all_cues:
            ambient_file = sfx_client.resolve_ambient(all_cues[:3])

    # Panels with script events but no audio (wordless panels / splash pages)
    # still need screen time — bed them with silence so the mixer emits a
    # timing entry and Phase 4 renders the panel. Without this, a fully
    # wordless page produces empty timing and zero video clips.
    covered = {ef["panel_id"] for ef in event_files}
    silent_durations: dict[int, float] = {}
    for e in script.events:
        if e.panel_id not in covered:
            silent_durations[e.panel_id] = (
                silent_durations.get(e.panel_id, 0.0) + (e.duration_sec or 0.0)
            )
    for panel_id, dur in silent_durations.items():
        # Clamp to [silent_min, silent_max]: a wordless panel is a brief beat,
        # never a long dwell from accumulated placeholder event durations.
        dur = min(max(dur, PACING["silent_min"]), PACING["silent_max"])
        silent_wav = wav_dir / f"silent_p{panel_id}.wav"
        tts._write_silence(silent_wav, duration_sec=dur)
        event_files.append({
            "event_id": f"sil_{panel_id}",
            "panel_id": panel_id,
            "wav_path": silent_wav,
            "kind": "silence",
            "pause_override": None,
        })

    # The mixer walks event_files sequentially — keep panels in script
    # (reading) order so the timeline matches the page.
    panel_order: dict[int, int] = {}
    for i, e in enumerate(script.events):
        panel_order.setdefault(e.panel_id, i)
    event_files.sort(key=lambda ef: panel_order.get(ef["panel_id"], 10_000))

    # Pacing-aware inter-panel pauses from the script's pause events
    panel_pauses: dict[int, float] = {}
    for e in script.events:
        if e.kind.value == "pause":
            panel_pauses[e.panel_id] = e.pause_override or e.duration_sec or 0.5

    # Mix
    narration_path = output_dir / "narration.wav"
    timing = mix_audio(
        event_files, ambient_file, narration_path,
        panel_ambients=panel_ambients,
        panel_pauses=panel_pauses,
    )

    # Write timing.json
    import json
    (output_dir / "timing.json").write_text(timing.model_dump_json(indent=2))

    return narration_path, timing
