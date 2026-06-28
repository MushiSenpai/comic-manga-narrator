# Voice engine decision — IndexTTS-2 (researched 2026-06-13)

Deeper comparison pass across the three finalists, scored for OUR exact use
case: offline quality-max, **per-character identity + per-scene emotion,
Japanese support (the product goal), commercial-safe, and co-resident with
Nemotron on one RTX 5090** (so VRAM matters — the lighter it is, the less
flush-juggling per the stack's single-model discipline).

## Decision matrix (all verified, with sources)

| Axis | **IndexTTS-2** ✅ | Higgs Audio V2 | Chatterbox (Multilingual/Turbo) |
|---|---|---|---|
| Emotion / "acting" | SOTA emotional fidelity (2025) | **Best raw** (75.7% win vs GPT-4o-mini-TTS) | emotion-*exaggeration* control; ranks below the other two on stability |
| **Timbre/emotion decoupling** | **YES — native, the unique feature** | no explicit decouple | no |
| Japanese | ✅ trained on ja (55k-hr ZH/EN/JA corpus) | ✅ 20+ langs incl ja | ✅ 23 langs incl ja |
| Voice cloning | on par with Higgs V2 / VibeVoice | excellent (5s, blind-test fooled family) | zero-shot |
| License (commercial) | **Apache-2.0** | Apache-2.0 (V2) — **but V3 is non-commercial** | **MIT** |
| VRAM | **~8GB (FP16)** → coexists with Nemotron-light | **18–20GB for cloning**, RTX 4090+ | **6GB** (Turbo 350M) — lightest |
| Extras | duration control | Llama-3.2-3B base, heavy | [laugh]/[cough] paralinguistic tags, sub-200ms |

## Verdict: lead with **IndexTTS-2**

It is the only finalist that is *uniquely* right rather than merely good:
- **The decoupling is exactly our architecture.** Set the character's voice
  with their reference clip and the scene's delivery with Nemotron's emotion
  description (or an emotion reference clip) — independently. That is the
  "double run" we hand-built (Parler→Seed-VC), collapsed into ONE Apache-2.0
  model with better quality and no fragile two-model cascade.
- **Japanese works** — clears the product goal that nearly disqualified it.
- **8GB** means it co-loads with Nemotron-light or slots cleanly into the
  flush-between discipline; Higgs's 18–20GB cloning footprint would force a
  flush on every batch.
- **Apache-2.0**, and unlike Higgs (whose V3 went non-commercial) there's no
  license-direction risk.

**Backups, ranked:** Higgs Audio V2 if IndexTTS-2's emotion underwhelms in
listening tests (accept the VRAM cost + stay on V2, not V3) → Chatterbox as
the lightweight/fast fallback (MIT, 6GB) if VRAM gets tight.

**What this retires:** the Track-H two-stage scaffold (Parler + Seed-VC, two
models, the torch/munch/torchcodec cascade, isolated venv) is no longer the
primary path — IndexTTS-2 does identity+emotion in one model. Keep the
orchestration layer's `TwoStageTTS` interface (render_audio already swaps
engines via it) and add an `IndexTTS2` engine behind the same interface.

## Integration plan (once /tmp is freed — see below)
1. Install IndexTTS-2 in an isolated venv (stable cu130 torch runs on the
   5090, proven in the Track-H prototype), or its own gateway container.
2. Add an `IndexTTS2TTS` engine implementing the `synthesize(text, voice_id,
   output_path, tone=, emotion=, ...)` contract; map Nemotron tone/emotion →
   IndexTTS-2's emotion description; voice_id → the character reference clip.
3. Wire it as the default behind `COMIC_TWO_STAGE_TTS`/a new `COMIC_TTS_ENGINE`
   flag; keep Fish Speech as the fallback.
4. A/B one Solo Leveling line: Fish vs IndexTTS-2 (neutral) vs IndexTTS-2
   (scene emotion) — the listening test that confirms the pick.

Sources: [index-tts](https://github.com/index-tts/index-tts) ·
[IndexTTS2.5 report](https://arxiv.org/html/2601.03888v3) ·
[IndexTTS2 review](https://dev.to/czmilo/indextts2-comprehensive-review-in-depth-analysis-of-2025s-most-powerful-emotional-speech-1m9e) ·
[Higgs V2](https://github.com/boson-ai/higgs-audio) ·
[Higgs V2 review](https://reviewnexa.com/higgs-audio-v2-review/) ·
[Chatterbox](https://github.com/resemble-ai/chatterbox) ·
[Chatterbox multilingual](https://www.resemble.ai/introducing-chatterbox-multilingual-open-source-tts-for-23-languages/) ·
[best open TTS 2026](https://findskill.ai/blog/best-open-source-tts-2026/)
