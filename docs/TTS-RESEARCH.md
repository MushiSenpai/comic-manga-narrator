# TTS research — what to use instead of / alongside Fish Speech 1.5

The review verdict on voices ("lifeless, no acting") is a model-capability
ceiling, not a tuning problem. Fish Speech 1.5 is a *voice-cloning* model:
it reproduces a timbre faithfully and reads text intelligibly, but it does
not act. This is the landscape for replacing or augmenting it, scoped to the
stack's hard constraint: **T1 sovereign — local, on the RTX 5090, commercial
-safe license.** No cloud TTS APIs (ElevenLabs et al.) — they fail the
sovereignty test that is the whole point of this stack.

## The shortlist (local, open, expressive)

| Model | License | Why it matters here | Watch-outs |
|---|---|---|---|
| **XTTS-v2 (Coqui)** | Coqui CPML (non-commercial) | Excellent zero-shot cloning + emotion/style transfer from the reference clip. | License blocks commercial use — usable for a personal/portfolio build, NOT a client deliverable. The community fork lineage is murky; check before shipping. |
| **F5-TTS** | **CC-BY (code/weights permissive)** | Strong cloning, fast, actively maintained, flow-matching architecture; more natural prosody than Fish 1.5 in side-by-sides. Good drop-in candidate. | Still "reads" more than "acts"; emotion comes from the reference clip, same as Fish. |
| **Fish Speech 1.6 / OpenAudio S1** | Apache-2.0 (1.5 line) — verify 1.6 | Newer Fish line claims explicit **emotion/tone markers** in-text (e.g. (angry), (whisper)) and better prosody. Lowest-friction upgrade — same gateway, same cloning workflow. | Verify the exact license of the newer weights before relying on it commercially. |
| **Kokoro-82M** | **Apache-2.0** | Tiny, fast, genuinely natural prosody for its size; great for the narrator. | No voice cloning (fixed voice set) — wrong tool for per-character casting, right tool for a polished narrator track. |
| **Parler-TTS** | **Apache-2.0** | Delivery is *described in a text prompt* ("a furious man shouting, fast and loud") — closest thing to directing an actor with words. Pairs perfectly with what Nemotron already extracts (tone/emotion). | No clone of a specific reference voice; you get described voices, not "this character's" voice. Quality variance. |

## Recommendation (concrete)

1. **Now, lowest-friction:** try **Fish Speech 1.6 / OpenAudio S1** at the
   existing gateway — if it honors in-text emotion markers, the pipeline
   already extracts `tone`/`dominant_emotion`, so wiring `(angry)`/`(whisper)`
   prefixes is a one-evening change and a real expressiveness jump with zero
   architecture change. **Verify the weights' license first.**
2. **Highest expressiveness ceiling:** prototype **Parler-TTS** for a few
   lines. It is the only option that *takes direction in words* — feed it the
   scene's emotion and intensity (which Nemotron sees) and it performs to
   that brief. The trade is losing per-character voice identity; the hybrid
   is Parler for emotional delivery + a similarity step to keep a consistent
   timbre, or Parler for the narrator and a cloner for characters.
3. **In parallel, cheapest real win on the CURRENT model:** the
   emotion-variant reference clips (ROADMAP B2). Even Fish 1.5 "acts" if its
   reference clip was recorded acting. Mine acted-emotion segments from
   LibriTTS-R (CC-BY) and clone `{voice}__angry.wav` etc. The mechanism is
   already built.

**Verdict:** the fastest perceptible jump is (1) a newer Fish/OpenAudio model
that takes emotion markers; the highest ceiling is (2) Parler-style
prompt-directed delivery. Do (3) regardless — it improves whatever model is
behind the gateway. All three keep the stack T1-sovereign.

---

# What else can Nemotron extract to make the result better?

The pipeline currently uses a fraction of what a forensic vision model can
report. Higher-leverage additions to the Pass 2 schema, roughly in order:

1. **`shot_type`** (extreme-closeup / closeup / medium / wide / establishing).
   This is the real fix for the camera: drive motion from the *director's
   framing*, not a guessed bbox. A wide establishing panel holds still; a
   closeup gets a slow push; an action panel gets energy. The artist already
   composed the shot — read it instead of re-inventing it.
2. **`action_intensity`** (calm / tense / impact / climax) per panel → drives
   SFX loudness, ambient swell, pacing, and shake. Solves "the fight panels
   feel the same as the talking panels."
3. **`dominant_emotion` USED** (already extracted!) → selects the emotion
   variant reference (B2) and the delivery prompt for an expressive TTS.
4. **`is_speaking` reliability + mouth/face point** → a precise halo/lower-
   third anchor; today the speaker bbox is whole-body and approximate.
5. **`sound_event` with intensity** (not just a label): "glass shattering,
   loud, close" → better Freesound query + mix level. Generalizes the
   action-sound fix.
6. **`scene_location` / `time_of_day` / `weather`** → coherent ambient beds
   across a run of panels instead of per-panel guesses.
7. **`reading_path` within a tall webtoon panel** (top→bottom beats) → lets a
   tall segment pan down through its beats instead of being one static frame
   or one zoom — the webtoon-native camera (ROADMAP F5).
8. **`speaker_continuity` hint** (same character as previous panel?) →
   stabilizes the cast map and avoids the crowd-scene explosion (F8).

The theme: we built a forensic extractor and then drove the render from
crude geometry. The biggest quality unlock is asking Nemotron for the
*director-level* signals (shot type, intensity, emotion, reading path) and
letting those drive camera, sound, and voice — instead of inferring them
downstream from bounding boxes.

---

# The two-stage idea (user's "double run") — YES, this is the right call

> "If Kokoro/Parler produce emotion precisely, why not generate with them,
> then clone to the character's voice with Fish Speech — emotion stays, voice
> changes?"

This is not a dumb question — it is **the established technique**, and it has
a name: **expressive TTS → voice conversion (VC)**. It is exactly how to
decouple *acting* from *identity*. Research confirms the pattern works
(arXiv 2103.16809 trains emotional VC on top of TTS for this exact reason;
Expressive-VC, arXiv 2211.04710, is built to carry prosody through the
conversion).

**How it maps to our stack — and the happy part: we already have the VC engine.**
The audio stack ships **RVC v2** (`/data/ai/02-models/audio/rvc/`), and RVC is
precisely a voice-conversion model: it takes *any* input audio and re-timbres
it to a target voice **while preserving the source's pitch contour, pace, and
emotion**. So the pipeline becomes:

```
Stage 1 — ACTING:   Parler-TTS ("a terrified young man whispering") OR an
                    emotion-prompted model produces an EXPRESSIVE take in
                    some generic voice. The performance lives here.
Stage 2 — IDENTITY: RVC (or Seed-VC) converts that take to the CHARACTER's
                    cloned timbre. Pitch/prosody/emotion of stage 1 are
                    preserved; only the vocal identity changes.
```

The character's voice is decided by Nemotron's cast label → a target RVC
model per character; the *emotion* is decided by the scene. Two knobs,
independently controlled — which is exactly what "actors act" requires and
what single-stage cloning (Fish 1.5) can't give us.

**Caveats (honest):**
- RVC preserves prosody well but can soften extreme emotion (laughs, sobs) —
  the 2025 literature notes emotional variance is only *partially* transferred.
  **Seed-VC v0.2** (Plachtaa/seed-vc) is the stronger modern option: explicit
  prosody-preservation control, beats RVCv2 on similarity, real-time capable —
  worth evaluating as the Stage-2 engine.
- It's two model passes per line (slower, more VRAM choreography) — fine at our
  episode-at-a-time cadence, a real cost at series scale.
- Quality compounds: a bad Stage-1 take converts into a bad-but-on-model take.

**Verdict:** this is the highest-ceiling path to "voices that act" AND stay
on-character, and it reuses RVC we already installed. Recommended build order:
Stage-1 = Parler-TTS (prompt-directed delivery, Apache-2.0), Stage-2 = Seed-VC
(or RVC v2 as the already-present fallback). This supersedes "just swap Fish
for a newer cloner" as the strategic direction.

Sources: arXiv 2103.16809 (TTS→emotional VC two-stage), arXiv 2211.04710
(Expressive-VC prosody transfer), github.com/Plachtaa/seed-vc (Seed-VC v0.2).
