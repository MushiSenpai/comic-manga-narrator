# Comic Narrator

AI pipeline that turns comic/manga pages into dramatized, narrated MP4 videos — fully local, running on the Mushishi sovereign AI stack (RTX 5090, Ubuntu 24.04).

A page image goes in; out comes a video where a camera drifts across each panel (Ken Burns + 2.5D speaker parallax) while cloned voices act out the dialogue, a narrator reads the captions, and ambient sound beds the scene.

## Pipeline

```
page.jpg
   │
   ▼  Phase 1 — Vision (Nemotron-3-Nano-Omni via vLLM :8000)
   │   Pass 1: panel detection (OpenCV gutters + Nemotron refinement)
   │   Pass 2: per-panel semantics (dialogue, characters, SFX, ambient cues)
   │   Pass 3: cross-panel cast consolidation
   ▼  page.json
   │
   ▼  Phase 2 — Script (events + voice auto-pick)
   ▼  script.json + cast.json
   │
   ▼  Phase 3 — Audio (Fish Speech 1.5 via audio gateway :9000, Freesound SFX)
   ▼  narration.wav + timing.json
   │
   ▼  Phase 4 — Video (ffmpeg: Ken Burns + parallax overlay + per-panel audio)
   ▼  output.mp4
```

## Requirements

| Dependency | Where |
|---|---|
| Nemotron NIM (vLLM, `:8000`) | `forensic-mode.sh` |
| Audio gateway + Fish Speech 1.5 (`:9000`) | `audio-mode.sh` |
| Freesound API key (optional — SFX/ambient) | `/data/ai/06-configs/comic-narrator/freesound.env` |
| FFmpeg ≥ 6.x | system |

**VRAM note:** Nemotron (~30 GB) and the audio stack cannot share the RTX 5090.
Run the pipeline in two passes using the resume flags (see below) — this mirrors
the stack's sequential forensic → creative handoff discipline.

## Usage

```bash
pip install -e ".[dev]"

# One-shot (requires both Nemotron and the audio gateway — only possible
# once a light agent-mode config exists; until then use the two-pass flow):
comic-narrator page.jpg --layout manga -o output.mp4

# Two-pass flow (current hardware reality):
# 1. forensic-mode.sh, then vision + script phases:
comic-narrator page.jpg --layout manga -o out.mp4 --keep-intermediates
#    (Phase 3/4 will warn and produce silence — page.json/script.json are the point)
# 2. audio-mode.sh light, then resume:
comic-narrator page.jpg --layout manga -o out.mp4 \
    --from-page-json page.json --from-script-json script.json

# Tests
pytest tests/ -v
```

## Voice bank

Voice *metadata* (gender/age/timbre for auto-pick) lives in
`/data/ai/06-configs/comic-narrator/voices/{voice_id}/voice.yaml`.
Voice *references* are gateway-side profiles: `/data/ai/02-models/audio/voices/{name}.wav`.
A voice_id is used as the TTS profile when a matching `{voice_id}.wav` profile exists;
otherwise everything falls back to the default profile (`avatar-v1`). Clone real
profiles via the gateway: `job_type=clone, profile_name=<voice_id>`.

## Status

Phases 0–5 complete and verified end-to-end (2026-06-10). Phase 6 (Hermes skill)
and Phase 7 (PDF → book scale) not started. See [docs/DEVLOG.md](docs/DEVLOG.md)
for the build history, issues found, and lessons learned.
