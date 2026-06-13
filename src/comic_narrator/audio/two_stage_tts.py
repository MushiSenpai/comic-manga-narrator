"""Track H — two-stage expressive voice: ACT then RE-VOICE.

The user's "double run" insight, which is the established expressive-TTS →
voice-conversion technique (arXiv 2103.16809, Expressive-VC). Single-stage
cloning (Fish Speech 1.5) reproduces a timbre but reads flatly. Splitting
the problem:

    Stage 1 (ACTING):   an expressive TTS performs the line with emotion in
                        a generic voice. The *performance* lives here, driven
                        by the scene's tone/emotion (which Nemotron extracts).
    Stage 2 (IDENTITY): a voice-conversion model re-timbres that take to the
                        CHARACTER's voice, preserving Stage 1's pitch contour,
                        pace and emotion. Only the vocal identity changes.

Two knobs, independently controlled — emotion (scene) and identity
(character) — which is what "actors act, on-character" requires.

This module is the ENGINE-AGNOSTIC orchestration layer. It mirrors
FishSpeechTTS.synthesize() so render_audio can use either path via config.
The concrete Stage-1/Stage-2 engines call the audio gateway (where the heavy
models live); when they're unavailable it falls back to Fish Speech so the
pipeline never hard-fails on a missing model.

Engine choices (see docs/TTS-RESEARCH.md):
  Stage 1: Parler-TTS  (Apache-2.0, prompt-directed delivery)
  Stage 2: Seed-VC v0.2 (zero-shot — converts using our EXISTING per-character
           reference clips with no training; the right fit for our voice bank)
           or RVC v2 (needs per-voice training — heavier to operate).
"""

from __future__ import annotations

from pathlib import Path

import requests

from comic_narrator.audio.tts_fish import FishSpeechTTS, _wav_duration
from comic_narrator.config import STACK_VOICE_DIR, DEFAULT_VOICE_PROFILE


# Nemotron tone/emotion → a natural-language delivery brief for Stage-1
# (Parler is *directed in words*). Keep these vivid; the description IS the
# performance instruction.
DELIVERY_BRIEF = {
    "shouting":   "shouting loudly and forcefully, high energy, fast",
    "loud":       "speaking loudly and emphatically",
    "excited":    "excited and energetic, fast and bright",
    "angry":      "angry and intense, sharp and forceful",
    "whispering": "whispering quietly, soft and breathy, slow",
    "nervous":    "nervous and hesitant, uneven pacing",
    "sad":        "sad and subdued, slow and heavy",
    "dismissive": "flat and dismissive, slightly bored",
    "confident":  "calm and confident, steady and clear",
    "":           "in a natural, expressive speaking tone",
}


def delivery_brief(tone: str, gender: str = "person") -> str:
    """Compose the Parler-style description prompt from Nemotron's tone."""
    manner = DELIVERY_BRIEF.get((tone or "").lower(), DELIVERY_BRIEF[""])
    subject = {"male": "A man", "female": "A woman"}.get(gender, "A person")
    return f"{subject} speaking, {manner}. Clear, close-mic, studio quality."


class TwoStageTTS:
    """Expressive-TTS → voice-conversion orchestrator (gateway-backed).

    Interface-compatible with FishSpeechTTS so render_audio can swap engines.
    `gender_of` lets the caller supply a per-event gender hint for the brief.
    """

    def __init__(self, gateway_url: str = "http://localhost:9000",
                 enabled: bool = True):
        self.gateway_url = gateway_url.rstrip("/")
        self.enabled = enabled
        self._fish = FishSpeechTTS(gateway_url)

    def health_check(self) -> bool:
        return self._fish.health_check()

    def _expressive_job(self, text: str, brief: str, target_profile: str,
                        output_path: Path) -> bool:
        """Submit the two-stage gateway job. Returns True on success.

        The gateway 'expressive_tts' worker runs Stage 1 (Parler with `brief`)
        then Stage 2 (Seed-VC toward target_profile's reference wav) and
        returns a single converted wav. Absent that worker, returns False so
        the caller falls back to Fish Speech.
        """
        try:
            r = requests.post(
                f"{self.gateway_url}/audio/job",
                data={
                    "job_type": "expressive_tts",
                    "text": text,
                    "description": brief,
                    "voice_profile": target_profile,
                },
                timeout=30,
            )
            if r.status_code == 400:
                return False  # worker/job_type not available
            r.raise_for_status()
            job_id = r.json().get("job_id", "")
            if not job_id:
                return False
            result = self._fish._poll(job_id)  # reuse the RQ poller
            out = (result or {}).get("output_file", "")
            if out and Path(out).exists():
                import shutil
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(out, output_path)
                return True
        except requests.RequestException:
            return False
        return False

    def synthesize(self, text: str, voice_id: str, output_path: Path,
                   speed: float = 1.0, emotion: str = "",
                   tone: str = "", gender: str = "person",
                   temperature: float = 0.85, top_p: float = 0.85) -> float:
        """Two-stage synth with Fish Speech fallback. Returns duration_sec."""
        target = self._fish.resolve_profile(voice_id, emotion)
        if self.enabled:
            brief = delivery_brief(tone, gender)
            if self._expressive_job(text, brief, target, output_path):
                return _wav_duration(output_path)
        # Fallback: single-stage Fish Speech (prosody params still applied).
        return self._fish.synthesize(
            text, voice_id, output_path, speed=speed, emotion=emotion,
            temperature=temperature, top_p=top_p,
        )

    def _write_silence(self, path: Path, duration_sec: float = 1.0):
        self._fish._write_silence(path, duration_sec)
