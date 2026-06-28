# Path to Publishable — status review + researched quality plan (2026-06-13)

The pipeline works end-to-end on real webtoons; the output is not yet good
enough to publish. This document reviews where the project actually is and —
grounded in current (2025–26) research — lays out the highest-leverage
changes to close the quality gap, mapped to what's already on the machine.

---

## 1. Where the project is

**Working, verified end-to-end:** webtoon/PDF/CBZ ingestion → Nemotron vision
(panels, dialogue, captions, SFX, ambient, characters, roles) → script →
Fish Speech TTS → Freesound SFX/ambient → Ken-Burns + speaker-halo video →
soft + translated subtitles → resumable book scale. 36 tests, CI, public repo.

**Fixed across the review rounds:** audio death after page 1 (book concat now
re-encodes), zoom-into-speech-bubble (panel detection rejects bubble-sized
regions), character voice consistency (cast-sheet re-identification: 23 labels
→ 8 identities, 0 inconsistent voices), pacing/dead-air, action-sound
extraction (fire/slash/impact), role-based casting.

**The honest quality gap (why it's not publishable):** three axes, in order
of how much they hurt.
1. **Voice — the dominant problem.** Fish Speech 1.5 clones timbre but reads
   flat; no acting. The two-stage Parler→Seed-VC prototype proved the
   *concept* but is fragile (two models, dependency cascade, isolated venv).
2. **Motion — still slideshow-ish.** Ken Burns + a halo is tasteful but flat;
   no real depth, no per-shot intent, hard cuts between panels.
3. **Soundscape — sparse.** SFX one-shots play but there is **no music bed**
   and ambient doesn't sustain under action panels, so silence dominates.

---

## 2. The single highest-leverage change: replace the voice engine

**IndexTTS-2** (github.com/index-tts/index-tts, open-sourced Sep 2025) is the
finding that reframes the whole voice problem:

- **Apache-2.0 — commercial use OK** (clears the T1-sovereign bar).
- **~8GB VRAM, FP16** — trivial on the RTX 5090, coexists with Nemotron-light.
- **Natively decouples emotion from speaker identity** — exactly the "double
  run" decoupling we hand-built, but in ONE model: give it the character's
  reference clip for *identity* and either a natural-language emotion
  description (which Nemotron already produces) OR an emotion reference clip
  for *delivery*. State-of-the-art emotional fidelity in 2025 evals.
- **Duration control** — useful for fitting narration to panel timing.

This makes the Track-H two-stage scaffold (Parler + Seed-VC, two models, the
torch/munch/torchcodec cascade) **obsolete as the primary path**: IndexTTS-2
gives emotion+identity control in a single Apache-2.0 model. Keep two-stage
as a documented fallback; lead with IndexTTS-2.

Runner-ups, if IndexTTS-2 disappoints in listening tests:
- **Higgs Audio V2** (BosonAI, Llama-3.2-3B based) — 75.7% emotion win-rate
  vs GPT-4o-mini-TTS; heavier.
- **Chatterbox** — won 65.3% blind vs ElevenLabs 24.5%; MIT; strong default.
- **Fish 1.6 / OpenAudio S1** — lowest-friction upgrade to the current gateway.

Sources: [index-tts repo](https://github.com/index-tts/index-tts),
[IndexTTS2 review](https://dev.to/czmilo/indextts2-comprehensive-review-in-depth-analysis-of-2025s-most-powerful-emotional-speech-1m9e),
[best open TTS 2026](https://findskill.ai/blog/best-open-source-tts-2026/),
[local TTS tested](https://localaimaster.com/blog/best-local-tts-models),
[Higgs/Modal](https://modal.com/blog/open-source-tts).

---

## 3. Structural accuracy: add a manga-specialist model

Nemotron *guesses* who is speaking. **Magi v2**
(github.com/ragavsachdeva/magi) is purpose-built for exactly our Pass-1/Pass-2
structure and does it better:

- Detects characters/text/panels, **orders panels**, **clusters characters**
  (re-identification), and **matches text to speakers using speech-bubble
  TAILS** — the artist's own who-is-talking cue, which we currently ignore.
- **Names characters** via a character bank (11.5K exemplar images, 76
  series) with a training-free constraint-optimisation method → consistent
  identity across a whole chapter (our cast-sheet does this heuristically;
  Magi does it natively and more accurately).

Best architecture: **Magi v2 for structure** (panels, reading order, speaker
attribution, character identity) + **Nemotron for the rich semantics**
(emotion, tone, scene, ambient cues, action sounds, shot intent). Each does
what it's best at; speaker-attribution errors — which directly cause wrong
voices — drop sharply.

Sources: [Magi repo](https://github.com/ragavsachdeva/magi),
[Tails Tell Tales (ACCV 2024)](https://arxiv.org/html/2408.00298v1),
[The Manga Whisperer](https://arxiv.org/html/2401.10224v1).

---

## 4. Motion: depth parallax + per-shot intent (we already own the pieces)

The craft consensus from motion-comic/recap production: **animate the
emotional beats, don't animate everything** — slow push-in on a face, pan
across an establishing shot, hard cut on an action beat, and **Z-axis depth**
so the foreground separates from the background (the "character comes out of
the picture" the review asked for).

- **DepthFlow** (github.com/BrokenSource/DepthFlow, open-source) and the
  **ComfyUI-Depthflow-Nodes** turn a still + a depth map into a true 2.5D
  parallax video. With **Depth Anything V2** (the `PARALLAX_METHOD` placeholder
  already in config) this replaces the flat halo/cutout with real depth — the
  single biggest motion upgrade, and it runs in the **ComfyUI we already have**.
- **LivePortrait** (Kuaishou, open-source, local) animates a face to speak —
  optional, for close-up dialogue panels, to get mouth movement on the
  speaker. Use sparingly (close-ups only) per the "beats not everything" rule.
- **Per-shot camera from `shot_type`** (ROADMAP G6): ask Nemotron for
  close/medium/wide and drive the move from the director's framing instead of
  guessed geometry — wides hold, close-ups push, action gets energy + a cut.

Sources: [DepthFlow](https://github.com/BrokenSource/DepthFlow),
[ComfyUI-Depthflow](https://github.com/akatz-ai/ComfyUI-Depthflow-Nodes),
[LivePortrait](https://github.com/KlingAIResearch/LivePortrait),
[motion-comic technique](https://reelmind.ai/blog/let-s-play-webtoon-comic-adaptation-to-dynamic-video),
[DancingBoard (arXiv 2503.09061)](https://arxiv.org/html/2503.09061v1).

---

## 5. Soundscape: add music, sustain ambient, mix properly

The most-cited immersion lever we're entirely missing is **background music**,
and the stack already ships three local music models — **YuE, ACE-Step,
Stable Audio Open** — completely unused by the narrator.

- **Score the scene**: a quiet bed under dialogue, tension under action,
  swell on reveals — generated locally from Nemotron's scene/emotion read.
  ACE-Step (fast) or Stable Audio Open (cinematic) fit the per-scene need.
- **Sustain ambient** under wordless action pages (the current gap: SFX hit
  then silence) so action never goes dead.
- **Mix discipline** (industry order): **Vocals → Music → Sound design**,
  with dynamic-range control so whispers survive and shouts don't clip, and
  music/ambient ducked under dialogue (we duck ambient already; add music).

Sources: [sound design for motion](https://mowe.studio/animation-sound-design-effects-music-motion-graphics/),
[mixing best practices](https://www.guvi.in/blog/sound-design-in-motion-graphics/),
[motion-comic audio](https://help.apiyi.com/en/what-is-manga-drama-ai-comic-guide-en.html).

---

## 6. Prioritized path to publishable

Ordered by quality-gained-per-effort, leading with the dominant problem.

1. **Swap the voice engine to IndexTTS-2.** Stand it up as a gateway worker
   (its own container, Apache-2.0, 8GB), feed it the character reference +
   Nemotron's emotion description. This is THE publish-blocker; one model
   replaces the fragile two-stage. *Effort: a focused session.*
2. **Add a music bed** from ACE-Step / Stable Audio (already installed),
   scored to scene emotion; sustain ambient under action; enforce the
   Vocals→Music→SFX mix order. *Effort: medium; huge perceptual lift.*
3. **DepthFlow 2.5D parallax** via ComfyUI + Depth Anything V2 — real depth
   motion instead of the flat halo. *Effort: medium.*
4. **Magi v2 for structure** (speaker attribution via bubble tails + character
   identity), Nemotron kept for semantics — fixes wrong-voice-from-wrong-
   speaker at the root. *Effort: a session; biggest accuracy win.*
5. **`shot_type`-driven camera** (G6) + clone more voices (G8) — polish.
6. **LivePortrait talking faces** on close-up dialogue panels — final polish,
   optional.

Do 1+2 first and re-judge: expressive voices + a music bed alone move the
output from "tech demo" toward "watchable." 3–6 take it to publishable.

---

## ⚠ Environment blocker (must fix before any render/commit)

`/tmp` is a **804MB tmpfs on the OS disk and is 100% full** — Bash cannot run
(it can't create its own output dir), so git/ffmpeg/python are all blocked.
This is why this review used only Read/WebSearch/Write. **Fix:** free `/tmp`
(stale pip/torch wheels from the Track-H installs are the likely culprit) or
set `CLAUDE_CODE_TMPDIR` to a dir on `/data` (700GB free). Until then, this
plan can't be committed or rendered.
