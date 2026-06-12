"""Shared camera trajectory — panel-space Ken Burns + speaker punch-in.

One function computes the crop rect for every output frame; the background
renderer (ken_burns.py) and the parallax overlay (parallax.py) both consume
it, so they can never drift apart. (v0.1 rendered the background with ffmpeg
zoompan and had to reverse-engineer its crop math frame-by-frame for the
overlay — including an undocumented even-snap. Owning the trajectory in
Python removes that whole failure class.)

Camera language:
- No speaker: gentle Ken Burns — zoom 1.0 → zoom_factor with a slow sine pan.
- Speaker present: ease (smoothstep) from the full panel frame toward a rect
  centered on the speaker, arriving at 80% of the clip and holding — the
  "punch-in" that makes dialogue panels read as shots, not slideshows.
"""

from __future__ import annotations

import math


def _smoothstep(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def base_rect(img_w: float, img_h: float, out_aspect: float) -> tuple[float, float]:
    """(w, h) of the largest out_aspect rect that fits inside the image."""
    if img_w / img_h > out_aspect:
        return img_h * out_aspect, float(img_h)
    return float(img_w), img_w / out_aspect


# A4 — pacing_hint → camera dynamics. arrive = fraction of the clip at which
# the punch-in lands; shake only fires on action peaks; zoom_mult scales the
# move's intensity. dramatic_reveal never stops creeping (arrive 1.0).
PACING_PROFILES = {
    "":                 (0.8, 0.0, 1.00),
    "action_peak":      (0.5, 3.0, 1.12),
    "dramatic_reveal":  (1.0, 0.0, 1.00),
    "quick_transition": (0.6, 0.0, 1.00),
}


def camera_rect(
    n: int,
    num_frames: int,
    img_w: int,
    img_h: int,
    speaker_bbox: tuple[int, int, int, int] | None = None,
    zoom_factor: float = 1.05,
    pan_fraction: float = 0.05,
    max_zoom: float = 1.5,
    subject_margin: float = 0.6,
    out_aspect: float = 16 / 9,
    pacing_hint: str = "",
) -> tuple[float, float, float, float]:
    """Crop rect (x, y, w, h) in image coords for output frame n.

    Framing rules (from real review feedback — the old version cropped into
    faces and felt artificial):
      * No speaker → show the WHOLE panel, only the gentlest Ken Burns drift.
      * Speaker present → the target frame is the speaker's bbox padded by
        `subject_margin` on every side, so the WHOLE BODY stays visible.
        - If the speaker already fills most of the panel, that padded target
          is ~the whole panel → the camera barely moves (a small page with
          one person gets only a slight push, never a face crop).
        - If the speaker is small in a large panel, the camera eases in to
          them — but never tighter than `max_zoom` (default 1.5×), so it
          stays a gentle move, not a punch into the face.

    speaker_bbox is in the SAME coordinate space as the image. The returned
    rect is always out_aspect and clamped inside the image.
    """
    arrive, shake_px, zoom_mult = PACING_PROFILES.get(
        pacing_hint, PACING_PROFILES[""]
    )
    bw, bh = base_rect(img_w, img_h, out_aspect)  # full-frame crop
    cx0, cy0 = img_w / 2.0, img_h / 2.0
    t = n / max(num_frames - 1, 1)

    if speaker_bbox is None:
        # Whole panel, gentlest drift.
        zf = 1.0 + (zoom_factor - 1.0) * zoom_mult
        z = 1.0 + (zf - 1.0) * (t if arrive >= 1.0 else _smoothstep(t / arrive))
        w, h = bw / z, bh / z
        cx = cx0 + math.sin(t * math.pi / 2.0) * pan_fraction * bw * 0.5
        cy = cy0
    else:
        sx, sy, sw, sh = speaker_bbox
        scx, scy = sx + sw / 2.0, sy + sh / 2.0

        # Target = subject padded by margin on all sides (whole body + air).
        tw = sw * (1.0 + 2.0 * subject_margin)
        th = sh * (1.0 + 2.0 * subject_margin)
        # Never tighter than max_zoom (smallest allowed crop).
        tw = max(tw, bw / max_zoom)
        th = max(th, bh / max_zoom)
        # Fit to output aspect by growing the short side.
        if tw / th < out_aspect:
            tw = th * out_aspect
        else:
            th = tw / out_aspect
        # Never larger than the full frame (big speaker ⇒ ~no zoom).
        tw, th = min(tw, bw), min(th, bh)

        # Ease from full frame → target; large subjects barely move.
        p = _smoothstep(t / arrive) if arrive < 1.0 else t
        w = bw + (tw - bw) * p
        h = bh + (th - bh) * p
        cx = cx0 + (scx - cx0) * p
        cy = cy0 + (scy - cy0) * p

    if shake_px > 0:
        cx += math.sin(n * 2.7) * shake_px
        cy += math.cos(n * 1.9) * shake_px

    x = min(max(cx - w / 2.0, 0.0), img_w - w)
    y = min(max(cy - h / 2.0, 0.0), img_h - h)
    return x, y, w, h
