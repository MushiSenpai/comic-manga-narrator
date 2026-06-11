#!/usr/bin/env python3
"""Comic Narrator — end-to-end pipeline orchestrator.

Phases 1–5 wired: page image → MP4 in a single command.
Phase 7 adds book-scale processing.
"""

from __future__ import annotations

import argparse
import sys
import json
from pathlib import Path

from comic_narrator import __version__
from comic_narrator.config import VOICE_BANK_DIR, SFX_CACHE_DIR, SFX_MAP_PATH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comic-narrator",
        description="AI pipeline: comic/manga pages → dramatized narrated MP4 videos",
    )
    parser.add_argument("--version", action="version", version=f"comic-narrator {__version__}")
    parser.add_argument("input", nargs="?", help="Comic page image (jpg/png) or book PDF")
    parser.add_argument("--layout", choices=["manga", "western"], default="manga")
    parser.add_argument("--lang", default="en")
    parser.add_argument("-o", "--output", default="output.mp4")
    parser.add_argument("--voice-bank", help="Override voice bank directory")
    parser.add_argument("--narrator-voice", default="_narrator")
    parser.add_argument("--no-cloud", action="store_true")
    parser.add_argument("--keep-intermediates", action="store_true")
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--panels", help="Use pre-made panels JSON (skip Pass 1)")
    parser.add_argument("--from-page-json", help="Skip Phase 1, use existing page.json")
    parser.add_argument("--from-script-json", help="Skip Phases 1-2, use existing script.json")
    parser.add_argument("--chapter-pages", help="Comma-separated page numbers for chapter splits")
    parser.add_argument("--vision-only", action="store_true",
                        help="Run Phases 1-2 only (page/script JSONs) — the Nemotron pass of the two-pass VRAM flow")
    parser.add_argument("--aspect", choices=["letterbox", "vertical-shorts"], default="letterbox")
    parser.add_argument("--freesound-key", help="Freesound API key (or set FREESOUND_API_KEY env)")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.input is None:
        parser.print_help()
        sys.exit(0)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {args.input}")
        sys.exit(1)

    output_path = Path(args.output)
    voice_bank = Path(args.voice_bank) if args.voice_bank else VOICE_BANK_DIR
    freesound_key = args.freesound_key or _load_freesound_key()
    is_pdf = (
        input_path.suffix.lower() in (".pdf", ".cbz", ".cbr", ".zip")
        or input_path.is_dir()
    )

    # ── Phase 1: Vision ──────────────────────────────────────────
    from comic_narrator.parse_page import parse_page
    from comic_narrator.schemas import PageAnalysis, PagePanels

    if args.from_page_json:
        page_json = json.loads(Path(args.from_page_json).read_text())
        page_analysis = PageAnalysis(**page_json)
        print(f"Loaded page.json from {args.from_page_json}")
    elif is_pdf:
        # Phase 7 — book scale
        from comic_narrator.scale import narrate_book
        chapter_pages = None
        if args.chapter_pages:
            chapter_pages = [int(x) for x in args.chapter_pages.split(",") if x.strip()]
        outputs = narrate_book(
            input_path, output_path,
            layout=args.layout,
            lang=args.lang,
            chapter_pages=chapter_pages,
            voice_bank_dir=voice_bank,
            narrator_voice_id=args.narrator_voice,
            freesound_api_key=freesound_key,
            vision_only=args.vision_only,
        )
        for o in outputs:
            print(f"  Output: {o}")
        sys.exit(0)
    else:
        print(f"Phase 1: Analyzing page: {input_path}")
        panels_override = None
        if args.panels:
            panels_data = json.loads(Path(args.panels).read_text())
            panels_override = PagePanels(**panels_data)

        page_analysis = parse_page(
            input_path, layout=args.layout, lang=args.lang,
            panels_override=panels_override,
        )
        if args.keep_intermediates:
            out_dir = output_path.parent
            (out_dir / "page.json").write_text(page_analysis.model_dump_json(indent=2))
        print(f"  Detected {len(page_analysis.panels_layout.panels)} panels")

    if args.review:
        print(json.dumps(page_analysis.model_dump(), indent=2))
        input("Review the analysis above. Press Enter to continue, Ctrl+C to abort...")

    # ── Phase 2: Script ──────────────────────────────────────────
    from comic_narrator.build_script import build_script
    from comic_narrator.schemas import Script, Cast

    if args.from_script_json:
        script_json = json.loads(Path(args.from_script_json).read_text())
        script = Script(**script_json)
        print(f"Loaded script.json from {args.from_script_json}")
    else:
        print("Phase 2: Building script...")
        script, cast = build_script(
            page_analysis,
            voice_bank_dir=voice_bank,
            narrator_voice_id=args.narrator_voice,
            lang=args.lang,
        )
        if args.keep_intermediates:
            out_dir = output_path.parent
            (out_dir / "script.json").write_text(script.model_dump_json(indent=2))
            (out_dir / "cast.json").write_text(cast.model_dump_json(indent=2))
        print(f"  Emitted {len(script.events)} events, {len(cast.members)} cast members")

    if args.vision_only:
        out_dir = output_path.parent
        (out_dir / "page.json").write_text(page_analysis.model_dump_json(indent=2))
        (out_dir / "script.json").write_text(script.model_dump_json(indent=2))
        print(f"Vision pass complete: {out_dir}/page.json + script.json. "
              "Re-run with --from-page-json/--from-script-json once the audio stack is up.")
        sys.exit(0)

    # ── Phase 3: Audio ───────────────────────────────────────────
    from comic_narrator.render_audio import render_audio

    print("Phase 3: Rendering audio...")
    narration_wav, timing = render_audio(
        script,
        voice_bank_dir=voice_bank,
        freesound_api_key=freesound_key,
    )
    print(f"  Audio: {narration_wav} ({timing.total_duration_sec:.1f}s)")

    # Subtitles (C3): always emit a sidecar .srt next to the output
    from comic_narrator.subtitles import write_srt
    from comic_narrator.config import PAGE_OVERVIEW_SEC
    srt_path = output_path.with_suffix(".srt")
    write_srt(timing, srt_path, offset_sec=PAGE_OVERVIEW_SEC)
    print(f"  Subtitles: {srt_path}")

    # ── Phase 4: Video ───────────────────────────────────────────
    from comic_narrator.render_video import render_video

    print("Phase 4: Rendering video...")
    render_video(
        input_path, page_analysis, timing, narration_wav, output_path,
    )
    print(f"  Output: {output_path}")

    # ── Cleanup ──────────────────────────────────────────────────
    if not args.keep_intermediates:
        # Clean per-event WAV files
        import shutil
        wav_dir = narration_wav.parent / "wavs"
        if wav_dir.exists():
            shutil.rmtree(wav_dir)

    print(f"\nDone! {output_path}")


def _load_freesound_key() -> str:
    """Load Freesound API key from env file or environment variable."""
    import os
    key = os.environ.get("FREESOUND_API_KEY", "")
    if key:
        return key
    env_file = Path("/data/ai/06-configs/comic-narrator/freesound.env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() == "FREESOUND_API_KEY":
                    return v.strip().strip('"').strip("'")
    return ""


if __name__ == "__main__":
    main()
