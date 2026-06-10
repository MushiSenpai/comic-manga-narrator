"""Pacing rules, voice defaults, and all configurable pipeline parameters."""

from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────

PROJECT_ROOT = Path("/data/ai/08-portfolio/comic-narrator")
CONFIG_ROOT = Path("/data/ai/06-configs/comic-narrator")
VOICE_BANK_DIR = CONFIG_ROOT / "voices"
SFX_CACHE_DIR = CONFIG_ROOT / "sfx-cache"
SFX_MAP_PATH = CONFIG_ROOT / "sfx_map.yaml"
FREESOUND_ENV_PATH = CONFIG_ROOT / "freesound.env"

# ── GPU / Services ──────────────────────────────────────────────────────

VLLM_URL = "http://localhost:8000/v1"
VLLM_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
AUDIO_GATEWAY_URL = "http://localhost:9000"
FISH_SPEECH_CONCURRENCY = 4  # concurrent TTS jobs via audio gateway

# Gateway-side voice profiles: the TTS worker resolves voice_profile names
# against /data/ai/02-models/audio/voices/{name}.wav (audio stack convention).
STACK_VOICE_DIR = Path("/data/ai/02-models/audio/voices")
DEFAULT_VOICE_PROFILE = "avatar-v1"

# ── Vision (Phase 1) ────────────────────────────────────────────────────

PANEL_DETECTION_MIN_AREA = 0.01   # fraction of image area
PANEL_DETECTION_GUTTER = 10       # min gutter width in pixels (at 300 DPI)
PAGE_DPI = 300                    # PDF render resolution

# ── Script / Pacing (Phase 2) ───────────────────────────────────────────

PACING = {
    "dialogue_breath": 0.5,       # seconds added after dialogue lines
    "caption_land": 1.0,          # seconds added after caption reads
    "sfx_min": 2.0,               # minimum sfx event duration
    "sfx_max": 4.0,               # maximum sfx event duration
    "silent_min": 2.0,            # minimum silent/visual panel
    "silent_max": 4.0,            # maximum silent/visual panel
    "inter_panel_pause_min": 0.3,  # minimum pause between panels
    "inter_panel_pause_max": 0.6,  # maximum pause between panels
}

# ── Audio Mixing (Phase 3) ──────────────────────────────────────────────

MIX_LEVELS = {
    "dialogue": 0.0,    # dB
    "caption": 0.0,     # dB (narrator)
    "sfx": -9.0,        # dB (midpoint of -6 to -12)
    "ambient": -18.0,   # dB
}

# ── Video (Phase 4) ─────────────────────────────────────────────────────

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 24
VIDEO_CODEC = "libx264"
VIDEO_BITRATE = "8M"
ASPECT_RATIO_MODE = "letterbox"  # "letterbox" | "fit_to_height" | "vertical_shorts"

# ── Ken Burns ───────────────────────────────────────────────────────────

KEN_BURNS_ZOOM_FACTOR = 1.05      # max zoom-in multiplier
KEN_BURNS_PAN_FRACTION = 0.05     # max pan as fraction of panel size

# ── Parallax ────────────────────────────────────────────────────────────

PARALLAX_SCALE = 1.08             # speaker layer scale-up
PARALLAX_SHIFT = 12               # max pixels to shift speaker layer
PARALLAX_METHOD = "cutout"        # "cutout" | "depth_anything_v2"

# ── Voice Auto-Pick (Phase 2) ───────────────────────────────────────────

# Maps Nemotron voice_attributes to voice bank voice_ids.
# Ordered by specificity — first match wins.
VOICE_MATCH_RULES = [
    # (attrs_subset, voice_id)
    (["male", "young", "bright"], "male_young_bright"),
    (["male", "young"], "male_young_bright"),
    (["male", "gruff"], "male_adult_gruff"),
    (["male", "adult"], "male_adult_gruff"),
    (["male"], "male_adult_gruff"),
    (["female", "young", "bright"], "female_young_bright"),
    (["female", "young"], "female_young_bright"),
    (["female", "warm"], "female_adult_warm"),
    (["female", "adult"], "female_adult_warm"),
    (["female"], "female_adult_warm"),
    (["monster"], "monster_deep"),
    (["object"], "monster_deep"),
]
DEFAULT_NARRATOR_VOICE = "_narrator"
DEFAULT_FALLBACK_VOICE = "male_adult_gruff"

# ── Minimum Viable Voice Bank ───────────────────────────────────────────

MVP_VOICE_BANK = [
    {"voice_id": "_narrator", "gender": "neutral", "age_approx": "adult",
     "pitch_category": "medium", "timbre_tags": ["warm", "clear"],
     "voice_type": "narrator"},
    {"voice_id": "male_young_bright", "gender": "male", "age_approx": "young",
     "pitch_category": "high", "timbre_tags": ["bright", "energetic"],
     "voice_type": "human"},
    {"voice_id": "male_adult_gruff", "gender": "male", "age_approx": "adult",
     "pitch_category": "low", "timbre_tags": ["gruff", "rough"],
     "voice_type": "human"},
    {"voice_id": "female_young_bright", "gender": "female", "age_approx": "young",
     "pitch_category": "high", "timbre_tags": ["bright"],
     "voice_type": "human"},
    {"voice_id": "female_adult_warm", "gender": "female", "age_approx": "adult",
     "pitch_category": "medium", "timbre_tags": ["warm"],
     "voice_type": "human"},
    {"voice_id": "monster_deep", "gender": "neutral", "age_approx": "adult",
     "pitch_category": "low", "timbre_tags": ["gruff", "gravelly", "deep"],
     "voice_type": "object"},
]
