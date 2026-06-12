"""Phase 3 — Audio rendering: Fish Speech TTS wrapper via audio gateway."""

from __future__ import annotations

import shutil
import time
import wave
from pathlib import Path

import requests

from comic_narrator.config import STACK_VOICE_DIR, DEFAULT_VOICE_PROFILE


def _wav_duration(path: Path) -> float:
    """Duration of a PCM WAV in seconds (0.0 if unreadable)."""
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())
    except (wave.Error, OSError):
        return 0.0


class FishSpeechTTS:
    """Calls Fish Speech 1.5 via the mushishi audio gateway at :9000.

    Fish Speech runs as the creative-tts container (:9002), fronted by the
    gateway; jobs are consumed by the audio-worker container off the RQ
    "voice" queue. The TTS worker selects voice references by *profile name*
    (resolved against /data/ai/02-models/audio/voices/{name}.wav) — it does
    not use per-job uploaded reference audio. Job status follows RQ states:
    queued → started → finished | failed, with the worker's return dict in
    the "result" field.
    """

    def __init__(self, gateway_url: str = "http://localhost:9000"):
        self.gateway_url = gateway_url.rstrip("/")

    def health_check(self) -> bool:
        """GET /audio/health → True if the gateway is up."""
        try:
            r = requests.get(f"{self.gateway_url}/audio/health", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    @staticmethod
    def resolve_profile(voice_id: str, emotion: str = "") -> str:
        """Map a voice bank voice_id (+ optional emotion) to a profile name.

        B2 emotion variants: Fish Speech cloning follows the *affect* of the
        reference clip, so "{voice_id}__{emotion}.wav" (e.g.
        male_young_bright__angry.wav) delivers the same character angry.
        Resolution: emotion variant → base profile → default. Clone variants
        via the gateway: profile_name={voice_id}__{emotion}.
        """
        if emotion and (STACK_VOICE_DIR / f"{voice_id}__{emotion}.wav").exists():
            return f"{voice_id}__{emotion}"
        if (STACK_VOICE_DIR / f"{voice_id}.wav").exists():
            return voice_id
        return DEFAULT_VOICE_PROFILE

    def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        speed: float = 1.0,
        emotion: str = "",
        temperature: float = 0.7,
        top_p: float = 0.7,
    ) -> float:
        """Submit TTS job, poll until finished, copy WAV. Returns duration_sec."""
        if not self.health_check():
            raise RuntimeError("Audio gateway is not reachable. Start with: audio-mode.sh")

        r = requests.post(
            f"{self.gateway_url}/audio/job",
            data={
                "job_type": "tts",
                "text": text,
                "voice_profile": self.resolve_profile(voice_id, emotion),
                "speed": str(speed),
                "temperature": str(temperature),
                "top_p": str(top_p),
            },
            timeout=30,
        )
        r.raise_for_status()
        job = r.json()
        job_id = job.get("job_id", "")
        if not job_id:
            raise RuntimeError(f"No job_id in response: {job}")

        max_wait = 120  # seconds
        interval = 2.0
        elapsed = 0.0
        while elapsed < max_wait:
            time.sleep(interval)
            elapsed += interval
            status_r = requests.get(
                f"{self.gateway_url}/audio/status/{job_id}", timeout=10
            )
            status_r.raise_for_status()
            status = status_r.json()
            state = status.get("status", "")

            if state == "finished":
                result = status.get("result") or {}
                if result.get("error"):
                    raise RuntimeError(f"TTS worker error: {result['error']}")
                output_file = result.get("output_file", "")
                if not output_file or not Path(output_file).exists():
                    raise RuntimeError(f"Job finished but output missing: {status}")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(output_file, output_path)
                return _wav_duration(output_path)

            if state in ("failed", "stopped", "canceled", "not_found"):
                raise RuntimeError(f"TTS job {state}: {status.get('error', 'unknown')}")

            # Exponential backoff
            interval = min(interval * 1.5, 10.0)

        raise TimeoutError(f"TTS job {job_id} did not complete within {max_wait}s")

    def synthesize_batch(
        self,
        events: list[dict],
        voice_bank_dir: Path | None = None,
        output_dir: Path = Path("."),
        concurrency: int = 4,
        progress_callback=None,
    ) -> list[Path]:
        """Synthesize all events sequentially. Returns WAV paths.

        voice_bank_dir is unused (voice references are gateway-side profiles)
        and kept for signature compatibility. Phase 7 adds concurrent batch.
        """
        output_paths: list[Path] = []
        total = len(events)

        for i, event in enumerate(events):
            voice_id = event.get("voice_id", "_narrator")
            out_path = output_dir / f"{event['event_id']}.wav"

            try:
                duration = self.synthesize(
                    text=event.get("text", ""),
                    voice_id=voice_id,
                    output_path=out_path,
                )
                event["duration_sec"] = duration
                output_paths.append(out_path)
            except Exception as e:
                print(f"  [WARN] TTS failed for event {event['event_id']}: {e}")
                # Create silent placeholder
                self._write_silence(out_path, duration_sec=1.0)
                output_paths.append(out_path)

            if progress_callback:
                progress_callback(i + 1, total)

        return output_paths

    def _write_silence(self, path: Path, duration_sec: float = 1.0):
        """Write a silent WAV file as placeholder."""
        sample_rate = 22050
        n_samples = int(sample_rate * duration_sec)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * n_samples)
