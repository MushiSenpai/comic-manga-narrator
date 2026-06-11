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

---

# Session 2 — 2026-06-11: real manga, one-pass mode, voices, book scale

## B2: killing the two-pass dance (six attempts)

A light agent-mode vLLM config now coexists with Fish Speech — full pipeline
in one command. The tuning saga (free-memory semantics, spec-drift rake №2,
`Model loading took 21.5 GiB` vs the documented ~18, and the profiling-pass
discovery: `--max-num-batched-tokens` 16384→4096 was the fix that mattered)
is written up as a standalone post: [BLOG-killing-the-two-pass-dance.md](BLOG-killing-the-two-pass-dance.md).
Final budget: vLLM 25.7 GiB (util 0.82, 32K ctx, KV 1.1 GiB / 76K tokens) +
Fish Speech 2.3 GiB + ~4 GiB headroom. New: `agent-mode.sh`,
`/data/ai/06-configs/vllm-nemotron-agent/`.

## Real manga page: two new bug classes

First run on a real One Piece page (PDF → 300 DPI): panel detection and
reading order were *fine*; Pass 2 scene description was *excellent*; and yet
zero dialogue/captions/SFX survived into the script.

**Bug 6 — the model echoed the prompt's key notation.** PASS2_SYSTEM described
fields as `"dialogues[]":` and Nemotron returned literal JSON keys
`"dialogues[]"`. The consumer's `data.get("dialogues")` quietly got nothing.
The synthetic-page runs had returned plain keys — model variance decided
which key style you get. Fixes: prompts now say `"dialogues" (array):`, and
`_parse_json()` normalizes any `key[]` → `key` (plus `_str_items()` for
captions that arrive as `{"text": ...}` dicts instead of strings).
*Lesson: any literal notation in your prompt's field list is a candidate
output key. Normalize on parse, not just on prompt.*

**Bug 7 — wordless panels had no screen time.** The mixer only emitted
timing entries for panels with audio events, so a wordless page produced
empty timing → zero clips → ffmpeg concat exit 183 (the same crash signature
as Session 1's "no TTS" failure — same root class: timing-empty is a reachable
state and Phase 4 must survive it). Fix in render_audio: voiceless panels get
a silent bed at `silent_min` pacing, and event_files are sorted into script
(reading) order before mixing.

## Voice bank: public datasets instead of recording gear

No microphones, no voice actors — solved with **CMU ARCTIC** (festvox.org):
studio-quality, unrestricted BSD-style license (commercial OK; Meta's
Expresso et al. are CC-NC and were rejected for license reasons), per-utterance
WAVs directly downloadable. Six archetype profiles cloned via the gateway
(`job_type=clone`): rms→`_narrator`, bdl→`male_young_bright`,
awb→`male_adult_gruff`, clb→`female_young_bright`, slt→`female_adult_warm`,
and rms pitched down 28% (ffmpeg asetrate/atempo) →`monster_deep`.
Distinct voices with zero code changes — `resolve_profile()` matches
voice_id → profile name as designed. Alternatives noted: VCTK (CC BY 4.0,
110 speakers) and Common Voice (CC0) if more variety is needed later.

## Phase 7 + Phase 6 landed

- `scale.py`: PDF → per-page work dirs → chapter MP4s; resumable at every
  artifact; `--vision-only` makes the two-pass flow work at book scale too;
  `--chapter-pages 12,25` splits chapters. CLI now accepts PDFs directly.
- Hermes skill at `~/.hermes/skills/media/comic-narrator/SKILL.md` — teaches
  the agent mode requirements, single page + book usage, and troubleshooting.
- Freesound key installed (gotcha: the env file must read
  `FREESOUND_API_KEY=<key>`, not a bare key — the loader parses `K=V` lines).

---

# Session 3 — 2026-06-11: rename, publication, refinement roadmap

- Project renamed `comic-narrator` → **`comic-manga-narrator`** (dir, GitHub
  repo, Hermes skill). Gotcha: an editable venv hardcodes absolute paths in
  its script shebangs — the venv had to be rebuilt after the move.
- GitHub repo created (`MushiSenpai/comic-manga-narrator`, private). First
  push was rejected by GitHub's email-privacy protection — commits carried a
  private email address. Resolution recorded in the repo history.
- POC critique captured into [ROADMAP.md](ROADMAP.md): four tracks —
  **A** immersive motion (panel-space framing, speaker punch-in, pop v2,
  pacing-driven dynamics), **B** emotional voice acting (tone→delivery params,
  emotion-variant references, book-level cast persistence), **C** Japanese
  source + subtitles (CC0 Common Voice ja voices, srt emission, local
  translation track), **D** ops. Key insight: the vision pass *already
  extracts* `tone`, `dominant_emotion`, `pacing_hint`, and speaker bboxes —
  Phase 3/4 simply don't consume them yet. The immersion gap is a consumer
  problem, not a vision problem.
- Voice sourcing documented in [VOICES.md](VOICES.md) (license cheat-sheet:
  the "110 speakers" set is VCTK/CC-BY/English; multilingual CC0 = Common
  Voice) + `scripts/curate-cv-voices.py` to turn a Common Voice dump into
  cloned gateway profiles.

## Session 3 addendum — forensic soundscape (Track E)

User insight captured as a design principle: ambient sound must come from
what is *visible* (birds near a harbor → gull cries), not just drawn text —
that's why a forensic-grade vision pass is in the loop at all. Pass 2 was
already deriving cues from the art; the flattening happened downstream.
Fixed: per-panel layered ambient beds (up to 2, 300ms fades, panel-spanning
overlays) replace the single page-wide bed; Freesound ambient queries now
target loopable 10-120s recordings (`"<cue> ambience"`, separate cache
namespace) instead of 0.5-10s SFX hits; the Pass 2 prompt demands a forensic
sound-source inventory. Verified on the harbor page: 4 distinct beds
downloaded and mixed. Remaining: visually-implied one-shot SFX (E3),
dialogue ducking (E4), curated sfx_map pins (E5).

---

# Session 4 — 2026-06-11: pacing, camera language, tone, subtitles

User feedback on the soundscape build: "wind blows from the east" should be
*followed by a wind sound*, and the mix was wall-to-wall dialogue — no
breathing room. Diagnosis: the mixer butt-joined event WAVs (the
`dialogue_breath`/`caption_land` constants existed in config, consumed by
nothing — the same dead-data pattern as `tone`). Shipped in one pass:

- **Pacing**: per-kind breathing gaps after every event; inter-panel pauses
  now come from the script's pacing-aware pause events (dramatic_reveal
  lingers, quick_transition cuts) instead of a flat 0.5s.
- **Caption sound cues**: captions naming an audible phenomenon (wind, waves,
  thunder, ...) trigger a one-shot Freesound cue right after the line, +3dB
  over SFX level — "the wind blows from the east… *woooosh*".
- **A1+A2 camera rewrite**: clips now frame the PANEL (cropped from the page),
  and panels with a speaker get a smoothstep punch-in that arrives at 80% and
  holds. Architecture win: `camera.py` owns the trajectory and BOTH the
  background renderer and the parallax overlay consume it (PIL → rawvideo →
  ffmpeg pipes), deleting ffmpeg zoompan — and with it the whole
  reverse-engineered crop-math/even-snap replication problem from v0.1.
  Vision bboxes are panel-relative, which is now exactly camera space: the
  panel→page mapping disappeared too.
- **B1 tone → delivery**: Pass 2's `tone` now reaches Fish Speech as a speed
  multiplier (shouting 1.10×, whispering 0.88×) and the mixer as per-event
  gain (+4dB shout, −6dB whisper). Stack-side: the gateway needed a `speed`
  Form field — the worker supported it all along, the gateway dropped it.
- **C1**: Pass 2 transcribes in the page's ORIGINAL language (`--lang ja`
  ready; Nemotron reads Japanese natively; needs Japanese voice profiles —
  see VOICES.md).
- **C3**: the mixer records absolute per-event spans (`Timing.events`);
  every render emits a sidecar `.srt` (captions + dialogue), pages merge
  into per-chapter `.srt` with cumulative video-duration offsets.
- Tests: 23 (camera invariants, anchoring regression in the new
  architecture, mixer breath/pause timing, SRT formatting). Test lesson:
  the punch-in clamps at image edges by design — a near-edge bbox in the
  test produced a "failure" that was actually correct behavior.

## Session 4 addendum — voice bank v2 + remaining polish tracks

- **Voice complaint addressed** ("the Indian/European voices"): bank rebuilt
  from LibriTTS-R dev-clean (CC BY 4.0, no terms gate — downloaded and used
  the same hour, unlike Common Voice/HF which need account+terms). Speaker
  selection was metadata-free: autocorrelation median-F0 across all 40
  readers, picked 7 by pitch ladder (108→237 Hz) + monster pitch-shift.
  Bank grew 6 → 8 (new: male_adult_warm, female_young_soft) with match
  rules. Profiles overwrite by name — zero pipeline changes.
- **E4** ducking: ambient beds drop 5dB under speech (120ms margins).
- **A3** drop shadow under the speaker cutout (blurred alpha, 8/12px offset).
- **A4** pacing profiles in camera.py: action_peak punches at 50% with 3px
  shake, dramatic_reveal creeps the full clip, quick_transition arrives early.
- Mirror note: us.openslr.org fails TLS (curl exit 60); openslr.elda.org works.

---

# Session 5 — 2026-06-11: expressions, foregrounded visual sounds, establishing shot

Three pieces of user feedback on the v4 sample, all shipped as separate
commits:

1. **"HMPH is an expression, not a spelling bee."** All-caps comics
   lettering made the TTS spell interjections out letter by letter. TTS
   input is now normalized — all-caps lines get sentence-cased and an
   interjection lexicon maps expressions to pronounceable forms
   (HMPH→humph, TCH→tsk, GRR→grrr...). Subtitles keep the author's
   original lettering; only the synthesis input changes. Test-writing
   lesson: sentence-initial interjections keep their capital — the first
   "failure" was a wrong test expectation, not wrong code.

2. **"The seagulls and the cow are drawn ON PURPOSE — make them heard."**
   The author draws sound sources so readers hear the scene; burying them
   at -18dB (ducked -23dB) in an ambient bed wasn't honoring that. New
   Pass 2 field `visual_sfx` (0-3 per panel, moment-sounds implied by
   visible action/creatures, distinct from continuous `ambient_cues`);
   build_script emits them as one-shot SFX events at -9dB — the same level
   as drawn sound text. E3 closed.

3. **"Show the full page first, then go into the boxes."** Every page
   render now opens with a ~3s establishing shot — the whole page
   pillarboxed on black with a slow push — before the camera goes panel by
   panel. The overview carries a silent AAC track so the concat demuxer
   sees uniform streams (mixed stream params are exactly the class of
   silent concat bug this project keeps meeting). Subtitle timestamps
   offset by the overview length in both single-page and book-merge paths.

## Session 5 addendum — two self-inflicted bugs, honestly logged

- **Bug 8 (tooling discipline):** an unanchored `str.replace` during the
  expression-normalization patch matched a comment that existed in TWO
  places and injected the interjection block twice — slicing
  `render_audio`'s body off its `return` (function returned None; pipeline
  crashed at tuple unpack). Tests stayed green because no unit test calls
  `render_audio` end-to-end. File rebuilt clean. Lessons: anchor patch
  targets uniquely, and integration seams need at least a smoke test.
- **Bug 9 (model variance, round 3):** when Nemotron's panel output isn't
  parseable JSON at all, `json_repair` returns a bare *string*; callers
  `.get()` on it and one bad sample silently voided an entire panel — this
  time the dialogue panel. `_parse_json` now rejects non-dict output with a
  retryable error and `parse_page` takes a second sample before stubbing
  (temperature 0.1 still has variance; the retry fixed it on the next run).
- Final verified render (59s): establishing shot → harbor panel with cow
  moo + seagulls + windmill creak (!) → ship panel with flag flap + wave
  crash → dialogue panel with punch-in, shouted "HEY, LUFFY!", humph'd
  HMPH, subtitles offset past the 3s overview.

---

# Session 6 — 2026-06-11: C2 — Japanese voices via Mozilla Data Collective

- Discovery: MDC's REST API has no list/search endpoint (only
  `/datasets/{id}`) and the site search is browser-rendered. Workaround:
  enumerate the **sitemap.xml** (792 dataset IDs) and resolve names via the
  authenticated details endpoint — exactly one Japanese voice dataset
  exists: *Common Voice Scripted Speech 25.0 – Japanese*
  (`cmn2hm68r01n4mm071qux43yu`, CC0).
- The API refuses downloads until the **account owner accepts the dataset's
  terms on its web page** — the SDK error message includes the exact URL,
  which is the right way to fail. (User accepted + downloaded via browser;
  15GB tarball, 584K clips, 300K validated rows.)
- `curate-cv-voices.py` fix: Common Voice TSVs exceed Python's default csv
  field limit (131072) — `csv.field_size_limit(sys.maxsize)`.
- Eight ja profiles cloned (3F/5M, twenties→fifties, real CV gender/age
  metadata in the profile names). Japanese TTS verified end-to-end through
  the gateway with `language=ja` — natural prosody from ~22s references.
- C2 closed. Next Japanese milestone: language-aware voice auto-pick + a raw
  Japanese page through `--lang ja` (C5).

---

# Session 7 — overnight autonomous run (2026-06-11 → 12)

Directive: "don't stop for approvals — refine voices, handle big formats,
finish what's left, document everything." Shipped, one commit per feature:

1. **Language-aware casting**: `match_voice` scores `{lang}_*` profiles by
   gender/age/timbre; ja narrator default; ja voice.yaml metadata.
2. **Full Japanese e2e** 🎌: synthetic vertical-text manga page (Noto CJK)
   → `--lang ja` single-pass → Japanese transcription (vertical bubbles
   read correctly), ja cast, Fish Speech ja audio, ja subtitles. Bug 10
   found en route: tied attribute scores collapsed the whole cast onto one
   profile via dict order — `match_voice` now takes an exclusion set.
   Verification lesson: re-running without `--keep-intermediates` leaves a
   STALE script.json; verify against fresh artifacts.
3. **Integration smoke test** (the bug-8 gap): phases 3→4 with TTS mocked
   at the class boundary — and it caught its first real regression hours
   later (B2's new kwarg broke the mock's signature).
4. **Big-format hardening**: `collect_pages()` accepts PDF / CBZ / ZIP /
   image folders ("someone dumps a file" now works); per-page failure
   tolerance with `failures.json` (a bad page can't kill a 200-page run;
   re-runs retry only failures); B3 book-level `cast_map.json` so a
   character keeps one voice across the whole book.
5. **Similarity casting** (`match-voice.py`): rank licensed voices by
   acoustic distance (F0, pitch spread, brightness) to a user-supplied
   reference. The voice-actor question answered the defensible way:
   cast the closest *licensed* voice; never clone the actor.
6. **B2 mechanism**: `{voice_id}__{emotion}.wav` variants resolve by tone
   bucket (shouting→angry...), falling back to base references.
7. **E5**: 12 common cues pinned to CC0 Freesound IDs — with name
   validation, because rating-sorted top hits included coins-falling for
   "rain falling" and a piano pedal for "creaking ship". The lottery is
   real; pin with eyes open.
8. **CI** (GitHub Actions pytest) and **docs/LESSONS.md** — 21 distilled
   takeaways across model integration, services, VRAM, media, voices,
   process.

## Session 7 addendum — C4 translated subtitles

Non-English pages now emit a second `.en.srt`: one batched Nemotron call
translates all speakable lines (register preserved — "おいルフィ！" became
"Oi Luffy!"), same timings via per-event text overrides, fail-soft (a
translation hiccup can never block a render). Verified on the Japanese
fixture: ja audio + ja subs + en subs from one command. Track C is now
C1-C4 complete; C5 (raw scanned Japanese pages) awaits real content.
