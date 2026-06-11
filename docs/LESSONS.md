# Lessons — the distilled version

Six development sessions, nine logged bugs, six releases. The full
play-by-play is in [DEVLOG.md](DEVLOG.md); this is the part worth carrying
to the next project, grouped by theme.

## Integrating against AI models

1. **Models echo your prompt's notation back at you.** Describe a field as
   `"dialogues[]"` and some samples return that literal key. Any structure
   you show in a prompt is a candidate output shape — normalize on parse,
   never only on prompt. (Bug 6: a real manga page lost ALL dialogue to
   this, silently.)
2. **Model output variance is a distribution, not a bug to fix once.**
   Same prompt, temperature 0.1: pixel bboxes vs normalized floats; plain
   keys vs `[]` keys; valid JSON vs none at all (json_repair returns a bare
   *string* for the latter — callers `.get()` and die). Coerce geometry,
   validate types at the parse boundary, and retry once per item before
   stubbing — a second sample usually lands.
3. **The model often already knows what your pipeline ignores.** Tone,
   emotion, pacing hints, and speaker boxes were extracted from day one and
   consumed by nothing. When output feels flat, check what you're dropping
   on the floor before adding new extraction.

## Integrating against services

4. **Write clients against the as-built service, not the spec — and not
   your own docs.** The audio gateway's real contract (RQ statuses, local
   output paths, profile-name-not-upload) differed from the spec in every
   detail that mattered; later, the stack's own architecture doc still
   listed two vLLM flags the deployment had removed (`--moe-backend
   triton`), and "weights ~18GB" was actually 21.5. Read the running
   system: `docker logs`, the gateway source, the boot line that says
   `Model loading took X GiB`.
5. **Prefer designs whose failure mode is loud.** libx264+alpha fails
   instantly (found in one run). A wrong status string polls to timeout and
   ships a silent video. ProRes 4444 was chosen over VP9 alpha for exactly
   this property: VP9 alpha silently decodes opaque without a decode flag.
6. **Queue systems need their consumer.** A gateway that enqueues to Redis
   does nothing without the worker container; jobs sit in `queued` and
   every symptom points elsewhere.

## VRAM engineering (single-GPU, multi-tenant)

7. **`gpu-memory-utilization` is a fraction of TOTAL VRAM validated
   against FREE VRAM at boot.** Another tenant's allocator bloat fails your
   startup even when steady state fits.
8. **The profiling pass is sized by config worst case, not workload.**
   `--max-num-batched-tokens` 16384→4096 freed the GiBs that six boot
   attempts of utilization-tweaking couldn't. Right-size the worst case to
   what you actually send (one image, short batches).
9. **Iterate on the error line, not the spreadsheet.** `Available KV cache
   memory: -1.62 GiB` told us exactly how far off we were; no VRAM
   arithmetic on paper did.

## Media pipelines

10. **Own your camera math.** Replicating ffmpeg zoompan's crop trajectory
    frame-by-frame required reverse-engineering an undocumented even-snap
    (4:2:0 chroma alignment). Deleting zoompan and computing the trajectory
    in one Python function consumed by BOTH the background and the overlay
    made misalignment structurally impossible.
11. **Concat demuxer wants uniform streams.** Every clip must match codec,
    pixel format, sample rate, channel count — the establishing shot
    carries a silent AAC track for exactly this reason. Empty concat lists
    (zero clips) are a reachable state; guard them.
12. **Audio is pacing.** Butt-joined TTS clips read as a slideshow. The
    fix wasn't better TTS — it was silence: per-kind breathing gaps,
    pacing-aware inter-panel pauses, ducked beds. The config constants for
    this existed unused for five sessions (see lesson 3).
13. **ALL-CAPS lettering is typography, not speech.** TTS spells out
    interjections ("HMPH" → aitch-em-pee-aitch). Normalize the synthesis
    input; keep the author's lettering for subtitles.

## Voice work

14. **License first, quality second.** The emotive corpora you want
    (RAVDESS, ESD, Expresso) are non-commercial; the usable set is CMU
    ARCTIC (unrestricted), LibriTTS-R / VCTK (CC BY), Common Voice (CC0).
    And cloning a real voice actor is a publicity-rights violation, not a
    feature — build similarity *casting* instead (match-voice.py).
15. **Metadata-free speaker selection works.** Autocorrelation median-F0
    over a few clips per speaker ranks a 40-reader corpus into a usable
    pitch ladder in minutes — no labels needed. Cloning follows the
    reference's accent AND affect: language needs native references;
    emotion variants are just differently-acted reference clips.
16. **Tie-breaks are casting decisions.** Equal attribute scores collapsed
    an entire Japanese cast (narrator included) onto dict-order's first
    profile. Diversity needs to be explicit: exclude already-used voices on
    ties.
17. **Datasets move.** Common Voice left Hugging Face in Oct 2025 (repos
    are pointer stubs now); the Data Collective API has no search endpoint
    (enumerate sitemap.xml), gates downloads behind a per-dataset web
    click, and CV TSVs overflow Python's csv field limit. Verify
    distribution channels live; training-era knowledge of *where data
    lives* goes stale fastest.

## Process

18. **"Code-complete" means nothing until it meets the live system.**
    Five integration bugs on first contact, all invisible to unit tests.
19. **Unit tests don't cover seams.** A function reduced to `return None`
    by a botched edit sailed through 24 green tests because nothing ran
    phases 3→4 together. The integration smoke test added afterward caught
    its first real regression within hours.
20. **Anchor your patches uniquely.** A text replacement matching a
    comment that existed twice injected a code block mid-function. Tooling
    discipline is correctness discipline.
21. **Document the journey, not just the state.** The DEVLOG's
    failure-by-failure record turned into the blog post, the release notes,
    and this file — and more than once, into the fix for a repeat bug
    ("we've met this rake before").
