"""Phase 7 — Book scale: PDF → per-page narrated videos → chapter MP4s.

Resumable by design: every page gets its own work directory holding the
intermediates (page.jpg, page.json, script.json, narration.wav, page.mp4).
A re-run skips any artifact that already exists, so a book interrupted at
page 40 resumes there — and the forensic↔audio VRAM handoff can be done
in two passes over the whole book (vision pass writes page/script JSONs,
audio pass consumes them) just like the single-page resume flags.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from comic_narrator.config import PAGE_DPI


def split_pdf(pdf_path: Path, pages_dir: Path, dpi: int = PAGE_DPI) -> list[Path]:
    """Render each PDF page to pages_dir/page_NNNN.jpg. Skips existing files."""
    import fitz  # PyMuPDF

    pages_dir.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []

    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            out = pages_dir / f"page_{i + 1:04d}.jpg"
            if not out.exists():
                pix = page.get_pixmap(dpi=dpi)
                pix.save(str(out), jpg_quality=92)
            out_paths.append(out)

    return out_paths


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def collect_pages(input_path: Path, pages_dir: Path, dpi: int = PAGE_DPI) -> list[Path]:
    """Turn whatever got dumped on us into an ordered list of page images.

    Accepts: a PDF (rendered at dpi), a CBZ/ZIP comic archive (image members
    extracted in name order — many .cbr files are actually zips and work
    too), or a directory of page images (name order). Resumable: existing
    outputs in pages_dir are reused.
    """
    import zipfile

    input_path = Path(input_path)
    suffix = input_path.suffix.lower()

    if suffix == ".pdf":
        return split_pdf(input_path, pages_dir, dpi=dpi)

    pages_dir.mkdir(parents=True, exist_ok=True)

    if suffix in (".cbz", ".zip", ".cbr"):
        try:
            zf = zipfile.ZipFile(input_path)
        except zipfile.BadZipFile:
            raise ValueError(
                f"{input_path.name} is not a zip archive. Real RAR-based .cbr "
                "files need unrar — convert to .cbz or extract to a folder."
            )
        with zf:
            members = sorted(
                m for m in zf.namelist()
                if Path(m).suffix.lower() in IMAGE_EXTS and not m.startswith("__MACOSX")
            )
            out_paths: list[Path] = []
            for i, m in enumerate(members):
                out = pages_dir / f"page_{i + 1:04d}{Path(m).suffix.lower()}"
                if not out.exists():
                    out.write_bytes(zf.read(m))
                out_paths.append(out)
            return out_paths

    if input_path.is_dir():
        images = sorted(
            p for p in input_path.iterdir() if p.suffix.lower() in IMAGE_EXTS
        )
        out_paths = []
        for i, src in enumerate(images):
            out = pages_dir / f"page_{i + 1:04d}{src.suffix.lower()}"
            if not out.exists():
                out.write_bytes(src.read_bytes())
            out_paths.append(out)
        return out_paths

    raise ValueError(f"Unsupported book input: {input_path}")


def group_chapters(n_pages: int, chapter_pages: list[int] | None) -> list[list[int]]:
    """Group 1-based page numbers into chapters.

    chapter_pages lists the first page of each chapter AFTER the first
    (e.g. [10, 25] → ch1: 1-9, ch2: 10-24, ch3: 25-end). None or empty →
    one chapter with every page.
    """
    pages = list(range(1, n_pages + 1))
    if not chapter_pages:
        return [pages]

    starts = sorted(set(p for p in chapter_pages if 1 < p <= n_pages))
    boundaries = [1] + starts + [n_pages + 1]
    return [
        list(range(boundaries[i], boundaries[i + 1]))
        for i in range(len(boundaries) - 1)
        if boundaries[i] < boundaries[i + 1]
    ]


def narrate_page_resumable(
    page_image: Path,
    work_dir: Path,
    layout: str,
    voice_bank_dir: Path,
    narrator_voice_id: str,
    freesound_api_key: str = "",
    vision_only: bool = False,
    lang: str = "en",
    prior_voice_map: dict[str, str] | None = None,
) -> Path | None:
    """Run phases 1-4 for one page, skipping any phase whose output exists.

    vision_only stops after script.json (Phases 1-2) — the Nemotron pass of
    the two-pass VRAM flow; a later run with the audio stack up picks up the
    JSONs and renders. Returns the page video path, or None in vision_only.
    """
    import json

    from comic_narrator.parse_page import parse_page
    from comic_narrator.build_script import build_script
    from comic_narrator.render_audio import render_audio
    from comic_narrator.render_video import render_video
    from comic_narrator.schemas import PageAnalysis, Script

    work_dir.mkdir(parents=True, exist_ok=True)
    page_json = work_dir / "page.json"
    script_json = work_dir / "script.json"
    cast_json = work_dir / "cast.json"
    narration_wav = work_dir / "narration.wav"
    page_mp4 = work_dir / "page.mp4"

    if page_mp4.exists():
        return page_mp4

    # Phase 1 — vision
    if page_json.exists():
        page_analysis = PageAnalysis(**json.loads(page_json.read_text()))
    else:
        page_analysis = parse_page(page_image, layout=layout, lang=lang)
        page_json.write_text(page_analysis.model_dump_json(indent=2))

    # Phase 2 — script
    if script_json.exists():
        script = Script(**json.loads(script_json.read_text()))
    else:
        script, cast = build_script(
            page_analysis,
            voice_bank_dir=voice_bank_dir,
            narrator_voice_id=narrator_voice_id,
            lang=lang,
            prior_voice_map=prior_voice_map,
        )
        script_json.write_text(script.model_dump_json(indent=2))
        cast_json.write_text(cast.model_dump_json(indent=2))

    if vision_only:
        return None

    # Phase 3 — audio (render_audio writes narration.wav + timing.json into work_dir)
    narration, timing = render_audio(
        script,
        voice_bank_dir=voice_bank_dir,
        freesound_api_key=freesound_api_key,
        output_dir=work_dir,
    )

    # Subtitles sidecar for this page (merged per chapter by narrate_book)
    from comic_narrator.subtitles import write_srt
    from comic_narrator.config import PAGE_OVERVIEW_SEC
    write_srt(timing, work_dir / "page.srt", offset_sec=PAGE_OVERVIEW_SEC)

    # Phase 4 — video
    render_video(page_image, page_analysis, timing, narration, page_mp4)
    return page_mp4


def narrate_book(
    pdf_path: Path,
    output_path: Path,
    layout: str = "manga",
    chapter_pages: list[int] | None = None,
    voice_bank_dir: Path | None = None,
    narrator_voice_id: str = "_narrator",
    freesound_api_key: str = "",
    vision_only: bool = False,
    lang: str = "en",
    progress_callback=None,
) -> list[Path]:
    """PDF book → one narrated MP4 per chapter.

    Work tree: {output_dir}/{output_stem}-work/
        pages/page_NNNN.jpg        rendered PDF pages
        page_NNNN/...              per-page intermediates + page.mp4

    Returns the list of chapter video paths. Single chapter → exactly
    [output_path]; multiple → output_stem_ch01.mp4, _ch02.mp4, ...
    """
    from comic_narrator.config import VOICE_BANK_DIR
    from comic_narrator.video.compose import concat_videos

    if voice_bank_dir is None:
        voice_bank_dir = VOICE_BANK_DIR

    import json as _json

    output_path = Path(output_path)
    work_root = output_path.parent / f"{output_path.stem}-work"
    page_images = collect_pages(Path(pdf_path), work_root / "pages")
    n_pages = len(page_images)
    print(f"Book: {n_pages} pages → {work_root}")

    # B3 — book-level cast map: a character keeps one voice everywhere
    cast_map_path = work_root / "cast_map.json"
    cast_map: dict[str, str] = (
        _json.loads(cast_map_path.read_text()) if cast_map_path.exists() else {}
    )

    page_videos: list[Path] = []
    failed_pages: dict[int, str] = {}
    for idx, page_image in enumerate(page_images, start=1):
        work_dir = work_root / f"page_{idx:04d}"
        already = (work_dir / "page.mp4").exists()
        print(f"Page {idx}/{n_pages}{' (cached)' if already else ''}...")
        try:
            video = narrate_page_resumable(
                page_image, work_dir, layout,
                voice_bank_dir, narrator_voice_id, freesound_api_key,
                vision_only=vision_only, lang=lang,
                prior_voice_map=cast_map,
            )
        except Exception as e:
            # One bad page must not kill a 200-page run — log and move on.
            failed_pages[idx] = f"{type(e).__name__}: {e}"
            print(f"  [FAIL] page {idx}: {failed_pages[idx]}")
            (work_root / "failures.json").write_text(
                _json.dumps(failed_pages, indent=2)
            )
            continue
        # Merge this page's resolved cast into the book map
        cast_json = work_dir / "cast.json"
        if cast_json.exists():
            for m in _json.loads(cast_json.read_text()).get("members", []):
                cast_map.setdefault(m["character_id"], m["voice_id"])
            cast_map_path.write_text(_json.dumps(cast_map, indent=2))
        if video is not None:
            page_videos.append(video)
        if progress_callback:
            progress_callback(idx, n_pages)

    if failed_pages:
        print(f"⚠ {len(failed_pages)} page(s) failed — see {work_root}/failures.json; "
              "re-run to retry just those pages (everything else is cached).")

    if vision_only:
        print(f"Vision pass complete: page/script JSONs in {work_root}. "
              "Re-run with the audio stack up to render.")
        return []

    chapters = group_chapters(n_pages, chapter_pages)
    outputs: list[Path] = []
    for ci, chapter in enumerate(chapters, start=1):
        if len(chapters) == 1:
            chapter_out = output_path
        else:
            chapter_out = output_path.with_name(
                f"{output_path.stem}_ch{ci:02d}{output_path.suffix}"
            )
        clips = [page_videos[p - 1] for p in chapter]
        if len(clips) == 1:
            shutil.copy(clips[0], chapter_out)
        else:
            concat_videos(clips, chapter_out)
        # Chapter subtitles: merge page .srt timings with cumulative offsets
        from comic_narrator.subtitles import write_book_srt, video_duration
        timing_jsons = [work_root / f"page_{p:04d}" / "timing.json" for p in chapter]
        durations = [video_duration(c) for c in clips]
        from comic_narrator.config import PAGE_OVERVIEW_SEC
        write_book_srt(timing_jsons, durations, chapter_out.with_suffix(".srt"),
                       per_page_offset_sec=PAGE_OVERVIEW_SEC)

        outputs.append(chapter_out)
        print(f"Chapter {ci}: pages {chapter[0]}-{chapter[-1]} → {chapter_out} (+ .srt)")

    return outputs
