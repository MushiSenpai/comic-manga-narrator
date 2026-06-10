#!/usr/bin/env python3
"""Curate Common Voice clips into voice-clone references.

Filters validated.tsv (up_votes, duration), groups by speaker (client_id),
builds one ~20s concatenated WAV per selected speaker, and optionally submits
clone jobs to the audio gateway.

Usage:
  curate-cv-voices.py /path/to/cv-corpus-XX-ja \
      --out /tmp/cv-ja-refs --lang ja --max-speakers 8 [--clone]

Requires: ffmpeg; the audio gateway (:9000) up for --clone.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

GATEWAY = "http://localhost:9000"


def clip_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("corpus", type=Path, help="extracted cv-corpus dir (contains clips/ + validated.tsv)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--lang", default="ja", help="profile name prefix")
    ap.add_argument("--max-speakers", type=int, default=8)
    ap.add_argument("--min-upvotes", type=int, default=2)
    ap.add_argument("--target-sec", type=float, default=20.0)
    ap.add_argument("--clone", action="store_true", help="submit gateway clone jobs")
    args = ap.parse_args()

    tsv = args.corpus / "validated.tsv"
    clips_dir = args.corpus / "clips"
    if not tsv.exists():
        sys.exit(f"not found: {tsv}")

    by_speaker: dict[str, list[dict]] = defaultdict(list)
    with open(tsv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            up = int(row.get("up_votes") or 0)
            down = int(row.get("down_votes") or 0)
            if up >= args.min_upvotes and down == 0:
                by_speaker[row["client_id"]].append(row)

    # Prefer speakers with metadata and plenty of clips
    ranked = sorted(
        by_speaker.items(),
        key=lambda kv: (bool(kv[1][0].get("gender")), len(kv[1])),
        reverse=True,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    made = 0
    for client_id, rows in ranked:
        if made >= args.max_speakers:
            break
        gender = (rows[0].get("gender") or "x")[:1]
        age = rows[0].get("age") or "adult"
        profile = f"{args.lang}_{gender}_{age}_{client_id[:6]}"

        picked: list[Path] = []
        total = 0.0
        for row in rows:
            p = clips_dir / row["path"]
            if not p.exists():
                continue
            d = clip_duration(p)
            if not 3.0 <= d <= 10.0:
                continue
            picked.append(p)
            total += d
            if total >= args.target_sec:
                break
        if total < 12.0:
            continue

        lst = args.out / f"{profile}.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in picked))
        ref = args.out / f"{profile}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-ar", "44100", "-ac", "1", str(ref)],
            check=True, capture_output=True,
        )
        print(f"{profile}: {len(picked)} clips, {total:.0f}s → {ref}")
        made += 1

        if args.clone:
            import requests
            r = requests.post(
                f"{GATEWAY}/audio/job",
                data={"job_type": "clone", "profile_name": profile},
                files={"voice_ref": open(ref, "rb")},
                timeout=30,
            )
            r.raise_for_status()
            print(f"   clone job: {r.json().get('job_id')}")

    if made == 0:
        sys.exit("no speakers passed the filters — relax --min-upvotes?")


if __name__ == "__main__":
    main()
