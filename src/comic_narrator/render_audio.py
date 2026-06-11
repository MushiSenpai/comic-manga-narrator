"""Phase 3 orchestrator: script.json + cast.json → narration.wav + timing.json."""

from __future__ import annotations

from pathlib import Path

from comic_narrator.schemas import Script, Timing
from comic_narrator.audio.tts_fish import FishSpeechTTS
from comic_narrator.audio.freesound import FreesoundClient
from comic_narrator.audio.mixer import mix_audio
from comic_narrator.config import VOICE_BANK_DIR, SFX_CACHE_DIR, SFX_MAP_PATH, PACING


# B1 — tone → (speed multiplier, gain dB). Pass 2 emits tone per dialogue;
# Fish Speech follows speed, the mixer applies gain.
TONE_DELIVERY = {
    "shouting":   (1.10, 4.0),
    "loud":       (1.05, 3.0),
    "whispering": (0.88, -6.0),
    "nervous":    (1.06, 0.0),
    "dismissive": (0.95, -1.0),
    "confident":  (1.00, 1.0),
}

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


def normalize_tts_text(text: str) -> str:
    """Make comics lettering speakable: de-caps + expand interjections."""
    import re
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


# Caption-triggered one-shot cues: when narration TEXT names an audible
# phenomenon ("THE WIND BLOWS FROM THE EAST"), play the sound right after
# the line — "wind blowing... woooosh".
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

    # TTS for dialogue + caption events
    tts = FishSpeechTTS()
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
        speed, gain_db = TONE_DELIVERY.get(ev.get("tone", ""), (1.0, 0.0))
        try:
            tts.synthesize(normalize_tts_text(ev["text"]), ev["voice_id"], out_wav, speed=speed)
            event_files.append({**ev, "wav_path": out_wav, "gain_db": gain_db})
        except Exception as e:
            print(f"  [WARN] TTS failed for {ev['event_id']}: {e}")

    # SFX events: resolve via Freesound
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


def normalize_tts_text(text: str) -> str:
    """Make comics lettering speakable: de-caps + expand interjections."""
    import re
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


# Caption-triggered one-shot cues ("THE WIND BLOWS..." → woooosh).
    # Inserted immediately after the caption that names the phenomenon, a
    # touch louder than the ambient bed so it reads as a cue, not texture.
    if freesound_api_key:
        import re as _re
        sfx_client = FreesoundClient(freesound_api_key, sfx_cache_dir, sfx_map_path)
        cued: list[dict] = []
        for ef in event_files:
            cued.append(ef)
            if ef.get("kind") != "caption":
                continue
            words = set(_re.findall(r"[a-z']+", ef.get("text", "").lower()))
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
        dur = max(dur, PACING["silent_min"])
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
