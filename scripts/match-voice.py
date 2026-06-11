#!/usr/bin/env python3
"""Similarity casting: find the licensed voice closest to a reference clip.

THE LEGAL LINE (read docs/VOICES.md "Voice-actor matching"): this tool does
NOT clone the person in the reference. Cloning a real voice actor from anime
audio violates their personality/publicity rights and the audio's copyright.
What this does instead is *casting*: it measures the reference's vocal
character (pitch, pitch variability, brightness) and ranks the voices you
are licensed to use (your cloned bank, or a CC0/CC-BY corpus directory) by
acoustic similarity. You get "the closest legal voice", not "their voice".

Usage:
  match-voice.py --ref /path/to/reference.{wav,mp3} \
      [--bank /data/ai/02-models/audio/voices] \
      [--corpus /path/to/extracted-corpus-clips-dir] \
      [--top 5]

Features per voice: median F0 (autocorrelation), F0 spread (expressiveness),
spectral centroid (brightness). Distance is normalized euclidean in that
3-space, F0 weighted double (pitch dominates perceived similarity).
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

BANK_DIR = Path("/data/ai/02-models/audio/voices")


def _load_mono(path: Path, max_sec: float = 30.0) -> tuple[np.ndarray, int]:
    """Decode any audio file to mono float samples via ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-t", str(max_sec),
             "-ar", "22050", "-ac", "1", tmp.name],
            check=True, capture_output=True,
        )
        with wave.open(tmp.name, "rb") as w:
            rate = w.getframerate()
            data = np.frombuffer(
                w.readframes(w.getnframes()), dtype=np.int16
            ).astype(np.float64)
    return data, rate


def voice_features(path: Path) -> dict | None:
    """(median F0, F0 std, spectral centroid) over voiced frames."""
    data, rate = _load_mono(path)
    if len(data) < rate:
        return None
    flen, hop = int(0.04 * rate), int(0.02 * rate)
    f0s, centroids = [], []
    freqs = np.fft.rfftfreq(flen, 1 / rate)
    for i in range(0, len(data) - flen, hop):
        fr = data[i:i + flen]
        if np.sqrt((fr ** 2).mean()) < 250:  # silence gate
            continue
        fr = fr - fr.mean()
        # F0 by autocorrelation (60-400 Hz)
        ac = np.correlate(fr, fr, "full")[flen - 1:]
        lo, hi = int(rate / 400), int(rate / 60)
        if hi < len(ac):
            lag = lo + int(np.argmax(ac[lo:hi]))
            if ac[lag] > 0.3 * ac[0]:
                f0s.append(rate / lag)
        # spectral centroid
        mag = np.abs(np.fft.rfft(fr * np.hanning(flen)))
        if mag.sum() > 0:
            centroids.append(float((freqs * mag).sum() / mag.sum()))
    if len(f0s) < 10:
        return None
    return {
        "f0_median": float(np.median(f0s)),
        "f0_std": float(np.std(f0s)),
        "centroid": float(np.median(centroids)) if centroids else 0.0,
    }


def distance(ref: dict, cand: dict) -> float:
    """Normalized weighted distance; pitch counts double."""
    df0 = abs(np.log2(cand["f0_median"] / ref["f0_median"]))     # octaves
    dvar = abs(cand["f0_std"] - ref["f0_std"]) / max(ref["f0_std"], 10.0)
    dcen = abs(cand["centroid"] - ref["centroid"]) / max(ref["centroid"], 200.0)
    return 2.0 * df0 + 0.5 * dvar + 0.5 * dcen


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ref", type=Path, required=True,
                    help="reference clip whose vocal character to match")
    ap.add_argument("--bank", type=Path, default=BANK_DIR,
                    help="dir of candidate voice WAVs (default: gateway bank)")
    ap.add_argument("--corpus", type=Path, default=None,
                    help="optional extra dir of candidate clips (e.g. corpus refs)")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    ref = voice_features(args.ref)
    if ref is None:
        raise SystemExit("could not extract voiced frames from the reference")
    print(f"reference: F0 {ref['f0_median']:.0f}Hz ±{ref['f0_std']:.0f}, "
          f"brightness {ref['centroid']:.0f}Hz\n")

    candidates: list[Path] = []
    for d in filter(None, [args.bank, args.corpus]):
        candidates += sorted(Path(d).glob("*.wav"))
    scored = []
    for c in candidates:
        feats = voice_features(c)
        if feats:
            scored.append((distance(ref, feats), c.stem, feats))
    scored.sort(key=lambda t: t[0])

    print(f"{'rank':4} {'dist':>6}  {'voice':28} {'F0':>5} {'±':>4} {'bright':>6}")
    for rank, (d, name, f) in enumerate(scored[:args.top], 1):
        print(f"{rank:4} {d:6.3f}  {name:28} {f['f0_median']:5.0f} "
              f"{f['f0_std']:4.0f} {f['centroid']:6.0f}")
    if scored:
        print(f"\ncast suggestion: '{scored[0][1]}' "
              "(closest licensed voice to the reference's vocal character)")


if __name__ == "__main__":
    main()
