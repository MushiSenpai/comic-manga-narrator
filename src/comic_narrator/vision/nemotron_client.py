"""Nemotron NIM client — 3-pass comic page analysis via vLLM.

Pass 1: Panel detection refinement (layout, sub-panels, irregular gutters).
Pass 2: Per-panel semantic extraction (dialogue, characters, SFX, scene).
Pass 3: Cross-panel cast consolidation (resolve character identity).
"""

from __future__ import annotations

import base64
import json
import json_repair
from pathlib import Path
from typing import Optional

from openai import OpenAI

from comic_narrator.schemas import (
    BBox,
    Cast,
    CastMember,
    Character,
    Dialogue,
    PagePanels,
    Panel,
    PanelAnalysis,
    PageAnalysis,
)
from comic_narrator.config import VLLM_URL, VLLM_MODEL


def _coerce_bbox(values, image_path: Optional[Path] = None) -> Optional[BBox]:
    """Build a BBox from model output, tolerating floats and normalized coords.

    Nemotron sometimes returns [x, y, w, h] as 0-1 fractions of the image
    despite the prompt asking for pixels — scale those by the image size.
    """
    try:
        vals = [float(v) for v in list(values)[:4]]
    except (TypeError, ValueError):
        return None
    if len(vals) < 4:
        return None
    if max(vals) <= 1.0 and image_path is not None:
        from PIL import Image
        with Image.open(image_path) as im:
            iw, ih = im.size
        vals = [vals[0] * iw, vals[1] * ih, vals[2] * iw, vals[3] * ih]
    x, y, w, h = (max(0, round(v)) for v in vals)
    return BBox(x=x, y=y, w=w, h=h)


def _normalize_keys(data: dict) -> dict:
    """Strip a literal trailing "[]" from keys.

    Nemotron sometimes echoes the prompt's array notation as the actual JSON
    key ("dialogues[]" instead of "dialogues"), which silently empties every
    field the consumers .get() by plain name.
    """
    if not isinstance(data, dict):
        return data
    return {
        (k[:-2] if isinstance(k, str) and k.endswith("[]") else k): v
        for k, v in data.items()
    }


def _str_items(items) -> list[str]:
    """Coerce a model-emitted list to strings ({"text": ...} dicts happen)."""
    out: list[str] = []
    for it in items or []:
        if isinstance(it, str):
            out.append(it)
        elif isinstance(it, dict):
            for key in ("text", "caption", "value"):
                if key in it:
                    out.append(str(it[key]))
                    break
    return out


# ── Prompt Templates ────────────────────────────────────────────────────

PASS1_SYSTEM = """You are a comic panel layout detector. Given a full comic/manga page image, output valid JSON with the layout direction and panel bounding boxes.

Rules:
- "layout": "manga" means right-to-left reading within rows, top-to-bottom.
- "layout": "western" means left-to-right reading within rows, top-to-bottom.
- Each panel has an "id" (integer), "bbox" as [x, y, width, height] in pixels.
- Include sub-panels and irregularly shaped panels.
- If you cannot determine exact bboxes, estimate based on visible gutters.
- Output ONLY the JSON object, no markdown fences, no explanation."""

PASS1_PROMPT = """Detect all panels in this comic page.
Return JSON: {"schema_version":"1.0","layout":"manga","panels":[{"id":1,"bbox":[x,y,w,h]},...]}
This is a {layout} reading-order page."""


PASS2_SYSTEM = """You are a comic/manga analysis engine. Given a cropped panel image, extract ALL semantic information.

Output valid JSON with these rules:
- "scene_description": 1-2 sentences describing the setting, time, weather, atmosphere.
- "characters" (array): every visible character. For each:
  - "label": a short unique label (e.g. "pirate_A", "luffy")
  - "expression": what their face shows ("angry", "smiling", "shocked", ...)
  - "dominant_emotion": the primary emotion ("rage", "joy", "fear", "surprise", "sadness", "neutral")
  - "voice_attributes": [gender, age, pitch, timbre_tags...] e.g. ["male","young","loud","bright"]
  - "voice_type": "human" for people, "object" for non-human speakers (figureheads, animals, monsters, robots)
  - "is_speaking": true if this character has dialogue in this panel
  - "is_visible": true if the character appears in the panel art, false if off-panel speaker
  - "bbox": [x, y, w, h] of the character's face/head in the panel (for parallax), null if not visible
- "dialogues" (array): each speech bubble. For each:
  - "speaker": must match a character "label"
  - "text": the exact dialogue text
  - "tone": delivery style ("shouting","whispering","dismissive","nervous","confident","neutral")
- "captions" (array): narrator text boxes (not spoken by characters)
- "sfx_text" (array): sound effect text art (e.g. "FWAP", "BOOM", "CRASH")
- "ambient_cues" (array): keywords for background ambient sound (e.g. "wind", "waves", "seagulls", "rain", "crowd")
- "pacing_hint": "dramatic_reveal", "quick_transition", "action_peak", or "" for normal pace

Output ONLY the JSON object, no markdown, no explanation."""

PASS2_PROMPT = "Analyze this comic panel and return the full semantic extraction JSON."


PASS3_SYSTEM = """You are a character identity resolver for comic/manga. Given per-panel analysis data from multiple panels, determine which character labels refer to the SAME person across panels and consolidate them into a cast list.

Rules:
- Characters with matching visual descriptions across panels are the same person.
- Assign each unique character a "character_id" (a short canonical name).
- "voice_id": assign from the available voice bank IDs based on voice_attributes.
- "voice_type": preserve from the panel analysis ("human", "object", "narrator").
- "appears_in_panels": list which panel_ids this character appears in.
- Include the narrator as a special cast member with voice_id set to narrator_voice_id.
- Output ONLY the JSON object."""

PASS3_PROMPT = """Given these panel analyses:
{panels_json}

Available voice bank IDs: {voice_bank_ids}
Narrator voice ID: {narrator_voice_id}

Resolve character identity across panels and return a consolidated cast JSON:
{{"schema_version":"1.0","narrator_voice_id":"{narrator_voice_id}","members":[...]}}
"""


# ── Client ──────────────────────────────────────────────────────────────

class NemotronClient:
    """Wraps the vLLM-Nemotron NIM for 3-pass comic analysis."""

    def __init__(self, base_url: str = VLLM_URL, model: str = VLLM_MODEL):
        self.client = OpenAI(base_url=base_url, api_key="not-needed")
        self.model = model

    def health_check(self) -> bool:
        """Check if the Nemotron NIM is reachable."""
        try:
            self.client.models.list()
            return True
        except Exception:
            return False

    def _encode_image(self, image_path: Path) -> str:
        """Read an image file and encode as base64 data URL."""
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        # Detect MIME type from extension
        suffix = image_path.suffix.lower()
        mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
        return f"data:{mime};base64,{b64}"

    def _call_nemotron(
        self,
        system_prompt: str,
        user_text: str,
        image_path: Optional[Path] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """Make a single chat completion call to Nemotron, optionally with an image."""
        messages = [{"role": "system", "content": system_prompt}]

        if image_path:
            data_url = self._encode_image(image_path)
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            })
        else:
            messages.append({"role": "user", "content": user_text})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def _parse_json(self, raw: str) -> dict:
        """Robust JSON parsing with repair fallback. Normalizes "key[]" keys."""
        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try json_repair for malformed JSON
            data = json_repair.loads(text)
        return _normalize_keys(data)

    # ── Pass 1: Panel Detection ─────────────────────────────────────

    def pass1_detect_panels(
        self, image_path: Path, layout: str = "manga"
    ) -> PagePanels:
        """
        Nemotron refines panel detection. Use as refinement after OpenCV.
        Or as primary if OpenCV fails (full-bleed layouts, irregular gutters).
        """
        raw = self._call_nemotron(
            system_prompt=PASS1_SYSTEM,
            user_text=PASS1_PROMPT.format(layout=layout),
            image_path=image_path,
        )
        data = self._parse_json(raw)
        panels = []
        for p in data.get("panels", []):
            bbox = _coerce_bbox(p.get("bbox") or [], image_path)
            if bbox is None:
                continue
            panels.append(Panel(
                id=p["id"],
                bbox=bbox,
                order_index=p.get("order_index", 0),
            ))
        detected_layout = data.get("layout", layout)
        return PagePanels(layout=detected_layout, panels=panels)

    # ── Pass 2: Per-Panel Semantic Extraction ───────────────────────

    def pass2_analyze_panel(self, panel_image_path: Path, panel_id: int) -> PanelAnalysis:
        """Extract all semantic info from a single cropped panel image."""
        raw = self._call_nemotron(
            system_prompt=PASS2_SYSTEM,
            user_text=PASS2_PROMPT,
            image_path=panel_image_path,
            temperature=0.1,
            max_tokens=4096,
        )
        data = self._parse_json(raw)

        characters = []
        for c in data.get("characters", []):
            char_bbox = None
            if c.get("bbox") and c.get("is_visible", True):
                char_bbox = _coerce_bbox(c["bbox"], panel_image_path)
            characters.append(Character(
                label=c.get("label", ""),
                expression=c.get("expression", ""),
                dominant_emotion=c.get("dominant_emotion", ""),
                voice_attributes=c.get("voice_attributes", []),
                voice_type=c.get("voice_type", "human"),
                is_speaking=c.get("is_speaking", False),
                is_visible=c.get("is_visible", True),
                bbox=char_bbox,
            ))

        dialogues = [
            Dialogue(speaker=d.get("speaker", ""), text=d.get("text", ""), tone=d.get("tone", "neutral"))
            for d in data.get("dialogues", [])
        ]

        return PanelAnalysis(
            panel_id=panel_id,
            scene_description=data.get("scene_description", ""),
            characters=characters,
            dialogues=dialogues,
            captions=_str_items(data.get("captions")),
            sfx_text=_str_items(data.get("sfx_text")),
            ambient_cues=_str_items(data.get("ambient_cues")),
            pacing_hint=data.get("pacing_hint", ""),
        )

    # ── Pass 3: Cast Consolidation ──────────────────────────────────

    def pass3_consolidate_cast(
        self,
        panels_analysis: list[PanelAnalysis],
        voice_bank_ids: list[str],
        narrator_voice_id: str = "_narrator",
        prior_cast: Optional[Cast] = None,
    ) -> Cast:
        """
        Resolve character identity across all panels.
        If prior_cast is provided (Phase 7), existing characters keep their voice_ids;
        only new characters get assigned.
        """
        # Build a compact representation of all panels for the prompt
        panels_summary = []
        for pa in panels_analysis:
            panels_summary.append({
                "panel_id": pa.panel_id,
                "characters": [
                    {"label": c.label, "expression": c.expression,
                     "voice_attributes": c.voice_attributes, "voice_type": c.voice_type}
                    for c in pa.characters
                ],
            })

        prior_context = ""
        if prior_cast and prior_cast.members:
            prior_context = f"\nExisting cast (keep these voice_ids — do NOT change them):\n{prior_cast.model_dump_json(indent=2)}\n"

        raw = self._call_nemotron(
            system_prompt=PASS3_SYSTEM,
            user_text=PASS3_PROMPT.format(
                panels_json=json.dumps(panels_summary, indent=2),
                voice_bank_ids=json.dumps(voice_bank_ids),
                narrator_voice_id=narrator_voice_id,
            ) + prior_context,
            temperature=0.0,
            max_tokens=2048,
        )
        data = self._parse_json(raw)

        members = []
        for m in data.get("members", []):
            members.append(CastMember(
                character_id=m.get("character_id", ""),
                canonical_name=m.get("canonical_name", ""),
                voice_id=m.get("voice_id", ""),
                voice_attributes=m.get("voice_attributes", []),
                voice_type=m.get("voice_type", "human"),
                appears_in_panels=m.get("appears_in_panels", []),
            ))

        return Cast(
            narrator_voice_id=data.get("narrator_voice_id", narrator_voice_id),
            members=members,
        )

    # ── Full 3-Pass Pipeline ────────────────────────────────────────

    def analyze_page(
        self,
        image_path: Path,
        layout: str = "manga",
        voice_bank_ids: Optional[list[str]] = None,
        prior_cast: Optional[Cast] = None,
        panels_override: Optional[PagePanels] = None,
    ) -> PageAnalysis:
        """
        Run the full 3-pass analysis on a comic page.

        Args:
            image_path: Path to the page image.
            layout: "manga" or "western".
            voice_bank_ids: Available voice IDs for cast assignment.
            prior_cast: Existing cast from previous pages (Phase 7).
            panels_override: Pre-made panels JSON (skip Pass 1 Nemotron call).

        Returns:
            PageAnalysis with panels_layout + panels_analysis.
        """
        if voice_bank_ids is None:
            voice_bank_ids = ["_narrator", "male_young_bright", "male_adult_gruff",
                              "female_young_bright", "female_adult_warm", "monster_deep"]

        # Pass 1: Panel detection
        if panels_override is not None:
            panels_layout = panels_override
        else:
            panels_layout = self.pass1_detect_panels(image_path, layout)

        # Pass 2: Per-panel semantic extraction
        panels_analysis: list[PanelAnalysis] = []
        for panel in panels_layout.panels:
            # We need cropped panel images — caller provides them via pass2_analyze_panel
            # For the full pipeline, use parse_page which handles cropping
            pass  # Individual panels called from parse_page.py

        # Pass 3: Cast consolidation (deferred to after all Pass 2 complete)
        cast = self.pass3_consolidate_cast(
            panels_analysis, voice_bank_ids,
            narrator_voice_id="_narrator",
            prior_cast=prior_cast,
        )

        return PageAnalysis(
            layout=panels_layout.layout,
            panels_layout=panels_layout,
            panels_analysis=panels_analysis,
        )
