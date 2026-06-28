"""IndexTTS-2 voice engine — expressive, single-model timbre/emotion decoupling.

The researched winner (docs/TTS-DECISION.md): IndexTTS-2 sets the character's
IDENTITY from a reference clip and the scene's EMOTION from an 8-dim vector,
independently — the "double run" decoupling in one Apache-2.0 model that does
Japanese and fits ~8GB. Replaces the fragile Parler+Seed-VC two-stage.

Interface-compatible with FishSpeechTTS so render_audio swaps engines via the
COMIC_TTS_ENGINE flag. Talks to the IndexTTS-2 server (its own venv/GPU);
falls back to Fish Speech per-line if the server is down, so renders never
hard-fail on a missing model.
"""

from __future__ import annotations

from pathlib import Path

import requests

from comic_narrator.audio.tts_fish import FishSpeechTTS, _wav_duration
from comic_narrator.config import STACK_VOICE_DIR, DEFAULT_VOICE_PROFILE

# IndexTTS-2 emotion vector order: [happy, angry, sad, afraid, disgusted,
# melancholic, surprised, calm]. Map Nemotron's tone to a vector. Values are
# intentionally moderate — the model biases/caps the sum internally.
_E = lambda **k: [k.get(n, 0.0) for n in
                  ("happy", "angry", "sad", "afraid", "disgusted",
                   "melancholic", "surprised", "calm")]
TONE_EMO_VECTOR = {
    "shouting":   _E(angry=0.6),
    "loud":       _E(angry=0.35, happy=0.15),
    "angry":      _E(angry=0.65),
    "excited":    _E(happy=0.6, surprised=0.15),
    "happy":      _E(happy=0.6),
    "whispering": _E(calm=0.5, melancholic=0.15),
    "nervous":    _E(afraid=0.45, surprised=0.1),
    "afraid":     _E(afraid=0.6),
    "sad":        _E(sad=0.6),
    "crying":     _E(sad=0.7),
    "surprised":  _E(surprised=0.6),
    "dismissive": _E(calm=0.3, disgusted=0.2),
    "confident":  _E(calm=0.4, happy=0.1),
    "":           _E(calm=0.5),
}


class IndexTTS2TTS:
    """Expressive single-model engine (timbre ref + emotion vector)."""

    def __init__(self, server_url: str = "http://127.0.0.1:9012",
                 gateway_url: str = "http://localhost:9000"):
        self.server_url = server_url.rstrip("/")
        self._fish = FishSpeechTTS(gateway_url)

    def health_check(self) -> bool:
        try:
            return requests.get(f"{self.server_url}/health", timeout=4).status_code == 200
        except requests.RequestException:
            return False

    def _spk_ref(self, voice_id: str) -> str:
        ref = STACK_VOICE_DIR / f"{voice_id}.wav"
        if not ref.exists():
            ref = STACK_VOICE_DIR / f"{DEFAULT_VOICE_PROFILE}.wav"
        return str(ref)

    def synthesize(self, text: str, voice_id: str, output_path: Path,
                   speed: float = 1.0, emotion: str = "", tone: str = "",
                   gender: str = "person",
                   temperature: float = 0.85, top_p: float = 0.85) -> float:
        """IndexTTS-2 synth (identity=voice_id ref, emotion=tone vector).

        Falls back to Fish Speech if the server is unreachable.
        """
        if self.health_check():
            try:
                emo_vec = TONE_EMO_VECTOR.get(tone, TONE_EMO_VECTOR[""])
                r = requests.post(
                    f"{self.server_url}/tts",
                    json={
                        "text": text,
                        "spk_ref": self._spk_ref(voice_id),
                        "out": str(output_path),
                        "emo_vector": emo_vec,
                        "emo_alpha": 1.0,
                    },
                    timeout=180,
                )
                r.raise_for_status()
                out = r.json().get("output_file", "")
                if out and Path(out).exists():
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    if str(output_path) != out:
                        import shutil
                        shutil.copyfile(out, output_path)
                    return _wav_duration(output_path)
            except requests.RequestException:
                pass  # fall through to Fish
        return self._fish.synthesize(
            text, voice_id, output_path, speed=speed, emotion=emotion,
            temperature=temperature, top_p=top_p,
        )

    def _write_silence(self, path: Path, duration_sec: float = 1.0):
        self._fish._write_silence(path, duration_sec)
