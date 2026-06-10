# Comic Narrator — Development Log & Lessons Learned

This document records how the project went from "code-complete on paper" to
verified end-to-end on the Mushishi stack, including every integration bug
found, the iterations it took, and the lessons worth keeping. Written for
anyone (including future-us) integrating against the same stack.

---

## Timeline

| Date | Milestone |
|---|---|
| 2026-06-10 (am) | Phases 0–5 code-complete: 2,171 lines, 21 modules, 4 unit tests, CLI with 15 flags. Never run against live services. |
| 2026-06-10 (pm) | First live integration session: 5 bugs found and fixed, first end-to-end MP4 produced. |
| 2026-06-10 (pm) | Parallax overlay reimplemented from scratch (the original could never have worked) — 10 tests passing. |

---

## Iteration history (live integration session)

### Run 1 — first contact with Nemotron
**Result:** crashed in Phase 2.

- `[WARN] Pass 2 failed for panel 3: validation errors for BBox` — Nemotron
  returned bbox coordinates as **0–1 normalized floats** (`[0.22, 0.3, 0.14, 0.18]`)
  despite the prompt explicitly asking for pixels. The Pydantic `BBox` schema
  (strict ints) rejected them and the whole panel's analysis was lost.
- `TypeError: build_script() got an unexpected keyword argument 'voice_bank_dir'`
  — the CLI orchestrator and the Phase 2 module had drifted apart; the code
  path had never been executed.

**Fixes:** `_coerce_bbox()` in `vision/nemotron_client.py` (accepts floats,
detects normalized coords and scales by image size, clamps negatives);
`build_script()` gained `voice_bank_dir` and now feeds the loaded bank into
`match_voice()` for voice_type-aware matching.

### Run 2 — vision and script phases clean
**Result:** Phases 1–2 perfect, Phase 4 crashed.

Nemotron's output quality was striking: every speech bubble and the caption
transcribed verbatim, ambient cue "waves" inferred from sea artwork, sensible
voice attributes per character. Phase 3 correctly warned the audio gateway was
down (Nemotron holds the GPU — expected). Phase 4 then failed in ffmpeg concat:
with zero TTS output the timing was empty, so no clips were generated and the
concat list was empty.

### Run 3 — audio handoff, first real TTS
**Result:** 13.4s of real Fish Speech narration; Phase 4 crashed in parallax.

After the VRAM swap (`audio-mode.sh`), all four TTS events synthesized
successfully through the gateway. Phase 4 then died:
`ffmpeg ... -c:v libx264 -pix_fmt yuva420p` → exit 234. **libx264 cannot
encode an alpha plane.** The parallax module had a 100% failure rate by
construction — it had simply never been run.

### Run 4 — first end-to-end MP4 ✅
With parallax temporarily disabled and per-panel audio offsets fixed:
9.7s h264+AAC video with real TTS narration. Pipeline verified end-to-end.

### Run 5 — parallax reimplemented properly
Full rewrite (see "The zoompan anchoring problem" below). 6 new unit tests
including a pixel-alignment regression test. 10/10 passing.

---

## Bugs found (all only discoverable by running against the live stack)

### 1. The audio gateway contract was imagined, not real
The TTS wrapper was written against the audio stack *spec*; the as-built
gateway differs in every detail that matters:

| Code expected | Gateway actually returns |
|---|---|
| `status: "complete"` | RQ statuses: `queued / started / finished / failed` |
| `output_url` to HTTP-download | `result.output_file` — a **local path** (host-visible via same-path bind mounts) |
| `duration_sec` in the status | nothing — compute it from the WAV locally |
| uploaded `voice_ref` file used for cloning | **ignored**; only `voice_profile` *names* resolving to `/data/ai/02-models/audio/voices/{name}.wav` |

Failure mode without the fix: every TTS job times out after 120s (the
status string never matches), the pipeline writes silent placeholders, and you
get a structurally valid but silent video. **Silent degradation, not a crash.**

### 2. `audio-mode.sh` never started the RQ worker
The gateway only *enqueues*. A separate `audio-worker` container consumes the
queues. The mode script started redis + gateway + fish-speech but not the
worker → every job queued forever. One-word fix in the compose-up line, but
the symptom (job stuck in `queued`) points everywhere except the cause.

### 3. Nemotron returns normalized bboxes when it feels like it
Same prompt, same page: some panels get pixel coords, others get 0–1 floats.
Treat every model-emitted geometry as untrusted input: coerce floats, detect
the ≤1.0 signature, scale, clamp.

### 4. Per-panel audio restarted from 0:00
Each panel clip mapped the full narration WAV with `-shortest` — so the
concatenated video replayed the beginning of the mix on every panel. Fix:
seek (`-ss entry.start_sec`) into the narration per panel clip.

### 5. Parallax: two independent fatal flaws
- **Codec:** alpha overlay encoded with libx264 + `yuva420p` — unsupported,
  fails on every invocation.
- **Geometry:** speaker bboxes are panel-relative, but the Ken Burns camera
  works in page space; the crop would have grabbed the wrong region even if
  the encode had worked.

---

## The zoompan anchoring problem (parallax rewrite)

The overlay must track ffmpeg `zoompan`'s exact crop trajectory or the
speaker cutout drifts off its background anchor. Naive replication left a
~2px offset. Ground truth was recovered by brute-force matching simulated
crops against actual rendered Ken Burns frames. The recovered semantics
(now in `_ken_burns_state()`):

- zoom at output frame *n* is `min(1 + 0.0005·(n+1), zoom_factor)` — the
  `z` expression sees the *previous* frame's zoom, so frame 0 is already 1.0005;
- crop dimensions are `floor(in/zoom)`;
- x/y are clamped against the **integer** crop dims, floored,
  then **snapped down to even values** — zoompan aligns crop offsets to the
  4:2:0 chroma grid of the decoded JPEG. Skipping the even-snap is the 2px drift.

Alpha intermediate format choice: **ProRes 4444 (.mov)** — ffmpeg's native
ProRes decoder carries alpha with no flags. VP9 alpha would silently decode
as opaque unless the consumer remembered `-c:v libvpx-vp9` before the input —
the same *class* of silent failure as the original libx264 bug. Choose formats
that fail loudly or work by default.

Regression test invariant: rendered with `scale_up=1.0, shift_px=0`, the
cutout must land exactly on its own background pixels — the test asserts a
±2px search finds zero as the best alignment at multiple timestamps.

---

## Operational lessons

1. **"Code-complete" means nothing until it has met the real services.**
   Five integration bugs, all invisible to unit tests and import checks, two
   of them silent-degradation rather than crashes.
2. **Write clients against the as-built service, not the spec.** The spec
   said `status: "finished"` + `result.output_file`; the wrapper was written
   against a remembered/idealized API. Read the gateway source first.
3. **Sequential VRAM discipline shapes the UX.** Nemotron (~30 GB) and the
   audio stack can't coexist on a 32 GB card. The resume flags
   (`--from-page-json`, `--from-script-json`) aren't conveniences — they're
   the mechanism that makes the forensic → audio handoff workable.
   Corollary: `--keep-intermediates` on a later run **overwrites** earlier
   intermediates; a degraded Phase 1 re-run clobbered a good `page.json`.
4. **Prefer encodings whose failure mode is loud.** libx264+alpha failed
   loudly (good — found in one run). A wrong status string failed silently
   into placeholder silence (bad — needed log reading to spot).
5. **Treat LLM-emitted geometry as untrusted input.** Coerce, validate,
   clamp, and drop gracefully — one bad bbox shouldn't void a panel's
   entire analysis.

---

## Current status & next steps

**Working:** full pipeline, page → narrated MP4 with Ken Burns + anchored
2.5D speaker parallax; 10 unit tests.

**Next (in rough priority order):**
1. **Freesound API key** — register, drop into
   `/data/ai/06-configs/comic-narrator/freesound.env`; SFX + ambient beds are
   implemented but currently skipped.
2. **Voice profiles** — clone per-archetype references via the gateway
   (`job_type=clone, profile_name=male_adult_gruff`, etc.). Until then all
   voices fall back to `avatar-v1`.
3. **Real manga/comic fixture** — current fixture is synthetic; validate
   panel detection + OCR on real scanned pages (manga RTL ordering path is
   untested against real art).
4. **Phase 6 — Hermes skill** so "narrate this page" works from the agent.
5. **Phase 7 — PDF book scale** (`scale.py`): page splitting, chapter
   batching, resumable book-level runs.
6. **Stack housekeeping:** light agent-mode vLLM config (EXECUTION-PLAN B2)
   would let Nemotron + Fish Speech coexist and kill the two-pass dance;
   `creative-lipsync` compose service needs a command (currently restart-loops).
