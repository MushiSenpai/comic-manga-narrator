# Voice Bank — sources, licensing, and how to add languages

## Current bank (rebuilt 2026-06-11 from LibriTTS-R)

Eight archetypes cloned from **LibriTTS-R** dev-clean (CC BY 4.0, restored
audiobook quality, US-neutral accents — replaced the CMU ARCTIC picks after
the Scottish/accented speakers read as off). Speakers were selected by
autocorrelation pitch analysis across all 40 dev-clean readers:

| Profile | Speaker | Median F0 | Character |
|---|---|---|---|
| `_narrator` | 2428 | 122 Hz | warm mid-deep male narrator |
| `male_adult_gruff` | 2803 | 108 Hz | deepest male |
| `male_adult_warm` | 3752 | 130 Hz | calm adult male |
| `male_young_bright` | 3170 | 146 Hz | higher energetic male |
| `female_adult_warm` | 6313 | 174 Hz | warm low female |
| `female_young_soft` | 7976 | 208 Hz | gentle mid female |
| `female_young_bright` | 2035 | 237 Hz | brightest female |
| `monster_deep` | 2803, pitched −28% | — | ffmpeg `asetrate` trick |

(The CMU ARCTIC section below is kept for provenance; those profiles were
overwritten in place — same names, zero code changes.)

Profiles live in `/data/ai/02-models/audio/voices/{name}.wav`; the TTS worker
selects them by name. Anything matching a `voice_id` is picked automatically.

## Japanese bank (installed 2026-06-11, C2 complete)

Eight speakers from **Common Voice Scripted Speech 25.0 – Japanese** (CC0,
via Mozilla Data Collective, dataset `cmn2hm68r01n4mm071qux43yu`), curated by
`scripts/curate-cv-voices.py` (≥2 upvotes / 0 downvotes, 3-10s clips, ~22s
references) and cloned through the gateway:

`ja_f_fourties_02a884`, `ja_f_fourties_a09e35`, `ja_f_fifties_7f373f`,
`ja_m_twenties_2e8835`, `ja_m_twenties_331023`, `ja_m_twenties_344712`,
`ja_m_thirties_3c9d94`, `ja_m_fourties_e5689a`

Verified: Fish Speech synthesizes natural Japanese from these references
(`language=ja` in the TTS job). Corpus on disk:
`/data/ai/03-data/audio/common-voice-ja/`. MDC API key:
`/data/ai/06-configs/comic-narrator/mdc.env` (`MDC_API_KEY`, used by the
`datacollective` SDK; note the per-dataset terms click must happen on the
website before any API download).

Remaining for full Japanese narration: map ja profiles into voice auto-pick
(language-aware `VOICE_MATCH_RULES` or a `--voice-bank` ja bank) and run a
raw Japanese page with `--lang ja` (ROADMAP C5 vertical-text validation).

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

**⚠ Updated 2026-06-11 — verified live.** As of **October 2025**, Mozilla
distributes Common Voice **exclusively via the Mozilla Data Collective**.
The old routes are dead ends: the Hugging Face repos
(`mozilla-foundation/common_voice_*`) are pointer stubs with no data, and
the commonvoice.mozilla.org datasets page forwards to the Collective.

**The one working route:**
1. Go to **https://mozilladatacollective.com** and create a free account.
2. Search for **"Common Voice"** and pick the *Japanese* entry of the
   newest corpus (e.g. "Common Voice Corpus 22.x – Japanese").
3. Accept the dataset terms on that page (the data itself is CC0) and
   download the tarball (`cv-corpus-*-ja.tar.gz`, a few GB).
4. Extract: `clips/*.mp3` + `validated.tsv` (columns: `client_id` = speaker,
   `path`, `sentence`, `up_votes`, `down_votes`, `age`, `gender`).

**Curation → profiles** (quality varies — webcam mics — so filter hard):
1. Keep clips with `up_votes ≥ 2, down_votes = 0`, duration 3-10s.
2. Group by `client_id`; keep speakers with ≥ 6 good clips; use `gender`/`age`
   columns to cover archetypes (young female, adult male, ...).
3. Concat ~20s per speaker, Demucs-clean, clone:
   `scripts/curate-cv-voices.py <extracted-dir> --out /tmp/cv-ja --lang ja --clone`
   automates 1-3 (see `--help`).
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

## Voice-actor matching ("can we sound like the anime?")

Anime adaptations mean an *official* voice exists for many characters. The
tempting shortcut — cloning the actual voice actor from anime audio — is
off the table on this stack, twice over: the recording is copyrighted, and
a person's voice is protected by personality/publicity rights (voice
cloning of identifiable real people without consent is exactly the misuse
case voice-cloning ethics policies name). T1-sovereign doesn't mean
rights-free.

The defensible version is **similarity casting**, and it's built:
`scripts/match-voice.py --ref <clip>` measures a reference clip's vocal
character (median F0, pitch variability, spectral brightness) and ranks the
voices you ARE licensed to use — your cloned bank and/or any CC0/CC-BY
corpus directory — by acoustic distance. You supply the reference clip from
your own legally-obtained media; the output is the closest *licensed* voice,
not a clone of the actor. With the 584K-clip Japanese Common Voice corpus on
disk, `--corpus` can search thousands of CC0 speakers for a closer match
than the 8 currently cloned.

Self-test: a bank voice used as its own reference ranks itself first at
distance ~0.005.
