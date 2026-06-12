"""Voice bank management — auto-pick, profile loading, voice matching."""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Optional

from comic_narrator.schemas import CastMember, VoiceProfile
from comic_narrator.config import (
    VOICE_MATCH_RULES,
    DEFAULT_NARRATOR_VOICE,
    DEFAULT_FALLBACK_VOICE,
    MVP_VOICE_BANK,
)


def load_voice_bank(voice_bank_dir: Path) -> dict[str, VoiceProfile]:
    """Load all voice profiles from a voice bank directory.

    Each subdirectory is a voice: {voice_id}/voice.yaml + {voice_id}/reference.wav
    Returns dict[voice_id, VoiceProfile].
    """
    profiles: dict[str, VoiceProfile] = {}

    if not voice_bank_dir.exists():
        return profiles

    for voice_dir in sorted(voice_bank_dir.iterdir()):
        if not voice_dir.is_dir():
            continue

        yaml_path = voice_dir / "voice.yaml"
        ref_path = voice_dir / "reference.wav"

        if yaml_path.exists():
            data = yaml.safe_load(yaml_path.read_text()) or {}
        else:
            data = {}

        voice_id = voice_dir.name
        profiles[voice_id] = VoiceProfile(
            voice_id=voice_id,
            gender=data.get("gender", "neutral"),
            age_approx=data.get("age_approx", "adult"),
            pitch_category=data.get("pitch_category", "medium"),
            timbre_tags=data.get("timbre_tags", []),
            voice_type=data.get("voice_type", "human"),
            reference_audio=str(ref_path) if ref_path.exists() else "",
        )

    return profiles


def init_voice_bank(voice_bank_dir: Path) -> dict[str, VoiceProfile]:
    """Initialize voice bank from MVP defaults if empty.

    Creates voice.yaml files for each MVP voice if no voices exist yet.
    """
    voice_bank_dir.mkdir(parents=True, exist_ok=True)

    existing = load_voice_bank(voice_bank_dir)
    if existing:
        return existing

    profiles: dict[str, VoiceProfile] = {}
    for vp_data in MVP_VOICE_BANK:
        voice_dir = voice_bank_dir / vp_data["voice_id"]
        voice_dir.mkdir(parents=True, exist_ok=True)

        yaml_data = {k: v for k, v in vp_data.items() if k != "voice_id"}
        (voice_dir / "voice.yaml").write_text(yaml.dump(yaml_data, default_flow_style=False))

        profiles[vp_data["voice_id"]] = VoiceProfile(
            voice_id=vp_data["voice_id"],
            **{k: v for k, v in vp_data.items() if k != "voice_id"},
        )

    return profiles


def _score_profile(profile: VoiceProfile, attrs_lower: list[str]) -> int:
    """Generic attribute scorer for language-scoped banks (no hardcoded ids)."""
    s = 0
    if profile.gender and profile.gender in attrs_lower:
        s += 4
    if profile.age_approx == "young" and ("young" in attrs_lower or "child" in attrs_lower):
        s += 2
    if profile.age_approx == "adult" and ("adult" in attrs_lower or "mature" in attrs_lower or "old" in attrs_lower):
        s += 2
    s += len({t.lower() for t in profile.timbre_tags} & set(attrs_lower))
    if profile.pitch_category and profile.pitch_category in attrs_lower:
        s += 1
    return s


def match_voice(
    voice_attributes: list[str],
    voice_type: str = "human",
    voice_bank: Optional[dict[str, VoiceProfile]] = None,
    lang: str = "en",
    exclude: Optional[set[str]] = None,
) -> str:
    """Auto-pick a voice_id from voice_attributes.

    Uses VOICE_MATCH_RULES (ordered by specificity, first match wins).
    If voice_type is not "human", prefers matching voice_type in bank.
    Falls back to DEFAULT_FALLBACK_VOICE.

    Args:
        voice_attributes: e.g. ["male", "young", "loud", "bright"]
        voice_type: "human" | "narrator" | "monster" | "object"
        voice_bank: optional loaded voice bank for type matching.

    Returns:
        voice_id string.
    """
    attrs_lower = [a.lower() for a in voice_attributes]

    # Language-scoped casting: when the page language isn't English and the
    # bank has {lang}_* profiles, pick among those by attribute score —
    # an English reference reading Japanese sounds wrong (cloning follows
    # the reference's accent).
    if lang and lang != "en" and voice_bank:
        prefix = f"{lang}_"
        candidates = [p for vid, p in voice_bank.items() if vid.startswith(prefix)]
        if candidates:
            # Rank by score; on ties prefer a voice nobody is using yet —
            # otherwise the whole cast (narrator included) collapses onto
            # whichever profile comes first in dict order.
            ranked = sorted(
                candidates,
                key=lambda p: _score_profile(p, attrs_lower),
                reverse=True,
            )
            for prof in ranked:
                if not exclude or prof.voice_id not in exclude:
                    return prof.voice_id
            return ranked[0].voice_id

    # If non-human, try to find matching voice_type in bank first
    if voice_type != "human" and voice_bank:
        for vid, profile in voice_bank.items():
            if profile.voice_type == voice_type:
                # Check if voice attributes also match
                for rule_attrs, rule_vid in VOICE_MATCH_RULES:
                    if all(a in attrs_lower for a in [ra.lower() for ra in rule_attrs]):
                        if rule_vid == vid or profile.voice_id == vid:
                            return vid
                # Type match without attr match
                return vid

    # Standard attribute matching (English archetype rules)
    chosen = DEFAULT_FALLBACK_VOICE
    for rule_attrs, voice_id in VOICE_MATCH_RULES:
        if all(a in attrs_lower for a in [ra.lower() for ra in rule_attrs]):
            chosen = voice_id
            break

    # Cast diversity for English too (bug 10 parity): if the rule landed on
    # an already-used voice and the bank has unused English profiles, take
    # the best-scoring free one instead — two gruff sailors should not share
    # a voice just because the rules tie.
    if exclude and chosen in exclude and voice_bank:
        lang_prefixes = ("ja_",)  # non-English banks live under lang prefixes
        free = [
            p for vid, p in voice_bank.items()
            if vid not in exclude
            and not vid.startswith(lang_prefixes)
            and not vid.startswith("_")
            and p.voice_type == voice_type
        ]
        if free:
            chosen = max(free, key=lambda p: _score_profile(p, attrs_lower)).voice_id

    return chosen


def resolve_cast_members(
    characters: list[dict],
    existing_cast: Optional[dict[str, str]] = None,
    voice_bank: Optional[dict[str, VoiceProfile]] = None,
) -> tuple[list[CastMember], dict[str, str]]:
    """Resolve voice assignments for a set of characters.

    Args:
        characters: list of dicts with 'label', 'voice_attributes', 'voice_type'.
        existing_cast: dict[label → voice_id] for previously resolved characters.
        voice_bank: optional loaded voice bank.

    Returns:
        (cast_members list, updated label→voice_id mapping).
    """
    label_map = dict(existing_cast) if existing_cast else {}
    members: list[CastMember] = []

    for char in characters:
        label = char.get("label", "")
        if not label:
            continue

        if label in label_map:
            voice_id = label_map[label]
        else:
            voice_id = match_voice(
                char.get("voice_attributes", []),
                char.get("voice_type", "human"),
                voice_bank,
            )
            label_map[label] = voice_id

        members.append(CastMember(
            character_id=label,
            canonical_name=char.get("canonical_name", label),
            voice_id=voice_id,
            voice_attributes=char.get("voice_attributes", []),
            voice_type=char.get("voice_type", "human"),
            appears_in_panels=char.get("appears_in_panels", []),
        ))

    return members, label_map
