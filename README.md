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

**VRAM note:** the *forensic* Nemotron config (~30 GB) cannot share the RTX
5090 with the audio stack. `agent-mode.sh` runs the light config (32K ctx,
~25.7 GB incl. KV) alongside Fish Speech, so the whole pipeline works in one
command. The two-pass resume flow remains for when forensic work owns the GPU.
See [docs/BLOG-killing-the-two-pass-dance.md](docs/BLOG-killing-the-two-pass-dance.md).

## Usage

```bash
pip install -e ".[dev]"

# Single pass (agent-mode.sh first — Nemotron light + Fish Speech coexist):
comic-narrator page.jpg --layout manga -o output.mp4

# PDF book (Phase 7): one MP4 per chapter, resumable per page:
comic-narrator book.pdf --layout manga -o book.mp4 --chapter-pages 12,25

# Two-pass fallback (forensic mode owns the GPU):
# 1. forensic-mode.sh, then the vision pass:
comic-narrator page.jpg --layout manga -o out.mp4 --vision-only
# 2. audio-mode.sh light, then resume:
comic-narrator page.jpg --layout manga -o out.mp4 \
    --from-page-json page.json --from-script-json script.json
# (PDF books: same dance with --vision-only, the work dir keeps per-page JSONs)

# Tests
pytest tests/ -v
```

## Voice bank

Voice *metadata* (gender/age/timbre for auto-pick) lives in
`/data/ai/06-configs/comic-narrator/voices/{voice_id}/voice.yaml`.
Voice *references* are gateway-side profiles: `/data/ai/02-models/audio/voices/{name}.wav`.
A voice_id is used as the TTS profile when a matching `{voice_id}.wav` profile exists;
otherwise everything falls back to the default profile (`avatar-v1`). All six MVP
archetypes are cloned from **CMU ARCTIC** speakers (unrestricted license,
festvox.org) — see DEVLOG Session 2. Add more via the gateway:
`job_type=clone, profile_name=<voice_id>`.

## Status

Phases 0–7 complete and verified end-to-end on real manga (2026-06-11),
including single-pass agent mode, PDF book scale, six cloned voice archetypes,
Freesound SFX, and the Hermes skill
(`~/.hermes/skills/media/comic-narrator/SKILL.md`). See
[docs/DEVLOG.md](docs/DEVLOG.md) for the build history and lessons learned.
