# Voice Bank — sources, licensing, and how to add languages

## Current bank (installed 2026-06-11)

Six archetypes cloned from **CMU ARCTIC** (festvox.org, unrestricted
BSD-style license, studio quality, English):

| Profile | Source speaker | Character |
|---|---|---|
| `_narrator` | rms | mature male, warm |
| `male_young_bright` | bdl | energetic young male |
| `male_adult_gruff` | awb | Scottish male, rough |
| `female_young_bright` | clb | bright female |
| `female_adult_warm` | slt | warm female |
| `monster_deep` | rms, pitched −28% | ffmpeg `asetrate` trick |

Profiles live in `/data/ai/02-models/audio/voices/{name}.wav`; the TTS worker
selects them by name. Anything matching a `voice_id` is picked automatically.

## Dataset license cheat-sheet (for a commercial/T1 stack)

| Dataset | License | Speakers | Languages | Verdict |
|---|---|---|---|---|
| CMU ARCTIC | unrestricted | 7 | en | ✅ in use |
| **VCTK** | CC BY 4.0 | **110** | en (accents) | ✅ if more English variety needed |
| **Common Voice** | **CC0** | thousands | **100+ incl. Japanese** | ✅ best license, variable quality |
| LibriTTS-R | CC BY 4.0 | ~2,400 | en | ✅ good for *emotive* mining (Track B2) |
| RAVDESS, ESD, Expresso | CC BY-**NC**(-SA) | — | — | ❌ non-commercial — rejected |

Note: "110 speakers" is **VCTK** (English-only). For Japanese and other
languages, the CC0 option is **Common Voice**.

## Common Voice: getting Japanese voices (CC0)

Two routes:

**Route 1 — official site (simplest):**
1. https://commonvoice.mozilla.org/ja/datasets → pick *Japanese* → enter an
   email → you get a direct tarball link (`cv-corpus-*-ja.tar.gz`, a few GB).
2. Extract: `clips/*.mp3` + `validated.tsv` (columns: `client_id` = speaker,
   `path`, `sentence`, `up_votes`, `down_votes`, `age`, `gender`).

**Route 2 — Hugging Face (scriptable):**
```bash
# one-time: accept the terms at
# https://huggingface.co/datasets/mozilla-foundation/common_voice_17_0
hf download mozilla-foundation/common_voice_17_0 \
  --repo-type dataset \
  --include "audio/ja/train/*" "transcript/ja/*" \
  --local-dir /data/ai/03-data/audio/common-voice-ja
```

**Curation → profiles** (quality varies — webcam mics — so filter hard):
1. Keep clips with `up_votes ≥ 2, down_votes = 0`, duration 3-10s.
2. Group by `client_id`; keep speakers with ≥ 6 good clips; use `gender`/`age`
   columns to cover archetypes (young female, adult male, ...).
3. Concat ~20s per speaker, Demucs-clean, clone:
   `scripts/curate-cv-voices.py` automates 1-3 (see `--help`).
4. Name profiles with a language prefix: `ja_female_young_bright.wav` etc.
   Then narrate with `--voice-bank` pointing at a ja bank, or extend
   `VOICE_MATCH_RULES` with language-aware ids (Track C2).

Fish Speech 1.5 is natively multilingual — a Japanese reference clip is all
it needs to speak Japanese with natural prosody. Do **not** reuse English
reference clips for Japanese lines; cloning follows the reference's accent.

## Emotion variants (Track B2 preview)

The cloning trick generalizes: Fish Speech follows the *affect* of the
reference. `male_young_bright/angry.wav` vs `.../neutral.wav` produces
audibly different deliveries of the same text. Mine emotive segments from
LibriTTS-R (CC BY 4.0 — acted audiobook emotion) rather than the NC-licensed
emotion corpora.
