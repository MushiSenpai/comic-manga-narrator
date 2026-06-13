# Roadmap — from POC to immersive narration

Status date: 2026-06-11. The POC is real: a manga PDF becomes a narrated MP4
in one command, on local silicon. This document is the honest gap list between
that POC and an *immersive* narration session, organized as four refinement
tracks plus the completed baseline. Each item has an acceptance test — "done"
means the test passes, not that code exists.

## Baseline — complete and verified

| Capability | Evidence |
|---|---|
| Panel detection + manga RTL reading order | real One Piece page, 3 panels, correct order |
| Vision extraction (dialogue/captions/SFX/ambient/cast) | all bubbles verbatim from a real scan |
| Voice auto-pick + cloned archetype bank (6 voices, CMU ARCTIC) | narrator/Luffy/crewman audibly distinct |
| Fish Speech TTS via gateway, Freesound SFX + ambient beds | 13.5s mixed narration track |
| Ken Burns + anchored 2.5D parallax | pixel-aligned overlay regression test |
| Single-pass mode (Nemotron-light + TTS coexist) | agent-mode.sh, 6-attempt tuning log in the blog post |
| PDF book scale, resumable, chapters | scale.py + tests |
| Hermes skill, Freesound key, git history | this repo |

---

## Track A — Immersive motion (the "2.5D doesn't pop" critique)

The current camera grammar is one timid move: a 1.05× page-space zoom with a
12px speaker drift. Panels with a ship get the same treatment as a shouted
line. The fix is a *camera language* driven by what the vision pass already
extracts (speaker bboxes, `pacing_hint`, `tone`, SFX) — the data is there,
unused.

| # | Item | Approach | Acceptance test |
|---|---|---|---|
| A1 | ✅ **Panel-space framing** | Ken Burns should frame the *panel*, zooming from panel bounds — not drift across the whole page. `ken_burns.py` takes the panel bbox as start/end rect. | Each panel clip shows that panel filling the frame. |
| A2 | ✅ **Speaker punch-in** | During a dialogue event, the camera eases toward the speaker bbox (pan+zoom to ~1.3-1.6×, ease-in-out cubic); pulls back to panel frame on pause events. Requires per-event (not per-panel) camera keyframes from `timing.json`. | Watching the manga page: camera visibly moves to Luffy when he speaks. |
| A3 | ✅(shadow) **Speaker pop v2** | Parallax overlay scales 1.15-1.25× with a soft drop shadow and 2-3px animated separation, eased — not a constant 1.08 sticker. Optionally Depth Anything V2 (`PARALLAX_METHOD="depth_anything_v2"` placeholder exists) for true background displacement. | Speaker reads as a foreground layer in motion, not a static cutout. |
| A4 | ✅ **Pacing-driven dynamics** | `pacing_hint` → motion profile: `action_peak` = fast push + 2-4px shake on SFX onset; `dramatic_reveal` = slow 8s creep; `quick_transition` = whip-pan to next panel. | The FWAP flag panel feels different from the harbor establishing shot. |
| A5 | **Directional transitions** | Replace hard concat cuts with slide/whip in reading direction (RTL for manga), 200-300ms. Needs xfade-based concat instead of `-c copy`. | No hard cut between panels 1→2→3. |

Effort: A1+A2 are the big wins and one focused session (camera math +
per-event keyframes). A3 cutout polish is half a day; depth variant is its
own session. A4/A5 are ffmpeg filter work.

## Track B — Emotional voice acting (the "voices ignore mood" critique)

Today the voice is chosen by gender/age **once per character** and every line
is delivered flat. But the vision pass already emits `tone` per dialogue
(shouting/whispering/nervous/...) and `dominant_emotion` per character —
both currently dropped on the floor in Phase 3.

| # | Item | Approach | Acceptance test |
|---|---|---|---|
| B1 | ✅ **Tone → delivery params** (+ prosody: temperature/top_p per tone, wired stack-wide) | Map `tone` to Fish Speech params per request: shouting → speed 1.15 + gain; whispering → speed 0.9 − gain; plumb a `speed`/params dict through the gateway TTS job (worker already accepts `speed`). | "HEY, LUFFY!" sounds shouted; a whisper sounds whispered. |
| B2 | ⏫ **Emotion-variant references** (TOP voice priority — review: voices are lifeless) | Per archetype, multiple reference clips: `male_young_bright/angry.wav`, `.../sad.wav`... Fish Speech cloning follows the reference's affect — the cheapest "emotion control" there is. Select by `dominant_emotion` with neutral fallback. Mine emotive segments from LibriTTS-R (CC BY 4.0 audiobooks contain acted emotion); most dedicated emotion corpora (RAVDESS, ESD) are NC-licensed — rejected. | Same character angry vs calm produces audibly different reads. |
| B3 | ✅ **Book-level cast persistence** | `scale.py` re-resolves voices per page; a character must keep one voice across a whole book (persist `cast.json` label→voice map in the work root, fuzzy-match labels across pages via Pass 3). | Luffy keeps his voice from page 1 to page 190. |
| B4 | **SFX vocalization choice** | "FWAP" is currently looked up on Freesound; some SFX read better *spoken* dramatically (Japanese manga tradition). Config flag per-SFX-class. | A/B render both modes. |

## Track C — Japanese source + subtitles (the actual product goal)

Goal: Japanese manga read aloud **in Japanese**, with subtitles (Japanese,
English, or both).

| # | Item | Approach | Acceptance test |
|---|---|---|---|
| C1 | ✅ **Keep source language** | `--lang ja` currently does nothing real. Pass 2 prompt: "transcribe dialogue in its original language, do not translate". Nemotron-3-Nano-Omni reads Japanese natively. | Raw Japanese page → script.json with Japanese text. |
| C2 | ✅ **Japanese TTS voices** | Fish Speech 1.5 is natively multilingual (ja is a headline language). Needs *Japanese reference clips* — a cloned English voice reading Japanese sounds wrong. Source: **Common Voice Japanese (CC0)** — see [VOICES.md](VOICES.md) for the concrete download/curation procedure. | Japanese line synthesized with natural ja prosody. |
| C3 | ✅ **Subtitle emission** | `script.json` events + `timing.json` already contain everything an `.srt` needs (per-event text + start/end). Emit `output.srt` always; `--burn-subs` runs the ffmpeg `subtitles` filter, default is soft-mux (`mov_text`). | MP4 plays with toggleable subs in VLC. |
| C4 | ✅ **Translated subtitle track** | During Phase 2, ask Nemotron for a translation per event (`text_translated`); emit a second `.srt`. T1-sovereign: translation stays on local Nemotron. | ja audio + en subtitles on one render. |
| C5 | **Vertical-text OCR validation** | Japanese manga uses vertical RTL text in bubbles; validate Pass 2 on raw (untranslated) scans, fix prompts if reading order inside bubbles scrambles. | 3 raw Japanese pages transcribed correctly. |

## Track E — Forensic soundscape (the "seagulls you can see but not read" principle)

The point of using Nemotron forensically: ambient sound should come from what
is *visible* in the art, not just from drawn sound text. A harbor panel with
birds should sound like a harbor with gulls.

| # | Item | Status |
|---|---|---|
| E1 | Visual ambient cues | ✅ Pass 2 derives cues from artwork (verified: harbor page → wind/birds/sea/waves/seagulls with zero ambient text in bubbles); prompt now demands a forensic sound-source inventory (2-5 cues per panel) |
| E2 | **Per-panel ambient beds** | ✅ 2026-06-11: each panel gets up to 2 layered beds over its own timeline span (300ms fades), replacing the single flattened page bed; Freesound ambient searches now target loopable 10-120s recordings, not SFX hits |
| E3 | Visually-implied SFX events | ✅ 2026-06-11: Pass 2 emits `visual_sfx` (seagulls → cries, cow → moo, flag → flap); build_script turns them into -9dB one-shot events — audible over the ducked beds |
| E4 | Dialogue ducking | ✅ 2026-06-11: beds drop 5dB under speech (120ms margins); lower ambient a further 4-6dB under dialogue/caption spans (pydub gain automation) so beds never fight the voices |
| E5 | Curated `sfx_map.yaml` growth | ✅ 2026-06-12: 12 common cues pinned to name-validated CC0 Freesound IDs; pin known-good Freesound IDs for the common cues (waves, wind, crowd, rain, seagulls) — text search top-hit is a lottery |

## Track F — Webtoon / vertical-scroll (Solo Leveling class)

Vertical-scroll webtoons are a different medium from paged comics: one tall
strip per "page", thousands of px tall, no panel grid.

| # | Item | Status |
|---|---|---|
| F1 | Native-res strip extraction (300-DPI render OOMs on tall strips) | ✅ webtoon.py extract_strips_native |
| F2 | Vertical gutter slicing → readable panel segments (cap + stride fallback) | ✅ 8 strips → 35 legible panels verified |
| F3 | Auto-detect webtoon PDFs (median h/w ≥ 2.5) + `--webtoon` / `--first-page`/`--last-page` | ✅ wired |
| F4 | Episode-boundary detection (no bookmarks in the wild PDF) — auto-split 4684 strips into 179 episodes | ⬜ for batch automation |
| F5 | Reading-cadence camera for webtoons: vertical pan within tall segments instead of panel punch-in | ⬜ webtoons read by scrolling, not cutting |
| F6 | Throughput: ~20.5k panels = ~14 days at current speed — D3 concurrency is a prerequisite for whole-series runs | ⬜ |
| F7 | Webtoon-aware silent cap: runs of wordless action panels stack `silent_min` into ~48s dead air — cap consecutive silent screen time | ⬜ stress test finding |
| F8 | Speaking-only cast filter: a 3-strip slice detected 23 "characters" (hand_A, monster_A...); voice map should keep only characters with dialogue | ⬜ stress test finding |
| F9 | VP9 .webm alpha intermediate instead of ProRes 4444 (~3GB/16s panel × 20.5k panels is untenable at series scale) | ⬜ stress test finding |

## Track G — Identity & visual grammar (review round 3)

| # | Item | Status |
|---|---|---|
| G1 | Character identity sheet: Pass 2 emits `appearance`, receives KNOWN CAST, reuses labels for recurring people → one person = one voice | ✅ cast_sheet.json fed to vision + persisted |
| G2 | bbox = character BODY, never the speech bubble (was zooming into chat bubbles) | ✅ prompt fixed |
| G3 | Dialogue ordered top-to-bottom by bubble position (comic reading order) | ✅ prompt fixed |
| G4 | Action panels with no speaker → halo the drawn SFX/impact symbol (`sfx_bbox`) | ✅ wired |
| G5 | Zoom ONLY when a page has multiple sub-panels (whole page → push into the active box); single-panel pages stay wide | ⬜ needs sub-panel detection within a segment |
| G6 | `shot_type` extraction drives camera (close/medium/wide) instead of geometry guessing | ⬜ TTS-RESEARCH extraction #1 |
| G7 | Role-based casting: protagonist→fixed lead voice, leads→distinct pool, background/crowd→shared voice (prominent mains, no cast explosion) | ✅ cast_voice() by Nemotron `role` |

## Track H — Two-stage expressive voice (the "double run")

| # | Item | Status |
|---|---|---|
| H1 | Stage-1 expressive TTS (Parler) + orchestration layer (two_stage_tts.py, gateway worker, config flag, Fish fallback) | ✅ code-complete; models install via scripts/install-expressive.sh |
| H2 | Stage-2 voice conversion. NOTE: the RVC dir is EMPTY (spec'd, never installed) and RVC needs per-voice training; **Seed-VC v0.2 is zero-shot and uses our existing reference clips directly** → recommended primary. RVC remains the user-preferred option to evaluate. | ⬜ install pending GPU-free |
| H3 | Per-character target VC model keyed by the cast sheet (G1) | ⬜ depends on G1 ✅ + H2 |

## Track D — Ops / scale

| # | Item | Notes |
|---|---|---|
| D1 | ✅ GitHub remote + CI | repo created; push pending email-privacy resolution; then a 10-line pytest workflow |
| D2 | Stack doc fold-in | agent-mode/B2 changes belong in mushishi-sovereign-ai-stack v1.8 (also: doc still lists the removed `--moe-backend triton` flags — twice bitten) |
| D3 | Long-book throughput | TTS events run sequentially; the gateway+RQ can take concurrent jobs (`FISH_SPEECH_CONCURRENCY=4` config exists, unused) |
| D4 | `creative-lipsync` service cleanup | vestigial container restart-loops; lipsync runs in audio-worker |
| D5 | Review UX | `--review` dumps raw JSON; a rendered contact-sheet (panels + detected text overlaid) would make corrections practical |

## Suggested order

1. **A1+A2** (panel framing + speaker punch-in) — biggest immersion jump per hour.
2. **B1** (tone → delivery) — data already flows, small patch, big perceptual win.
3. **C1+C2+C3** (Japanese + srt) — the product goal; C3 is trivial, C2 needs voice curation.
4. **A3-A5, B2** — polish passes.
5. **B3, C4, C5, D-track** — book-scale hardening.
