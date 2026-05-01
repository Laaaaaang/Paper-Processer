from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .config import AppConfig
from .io_utils import save_json, save_text
from .llm_client import create_analysis_for_config
from .models import AnalysisPacket, PaperPacket
from .obsidian import write_note
from .pdf_metadata import extract_pdf_metadata
from .rendering import render_full_note, render_note
from .zotero_api import ZoteroClient


ProgressCallback = Optional[Callable[[str], None]]


@dataclass
class IngestRequest:
    pdf_path: Path
    title: str
    authors: List[str]
    year: Optional[str] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    annotation_text: Optional[str] = None
    tags: Optional[List[str]] = None
    status: str = "inbox"
    item_type: str = "journalArticle"
    zotero_item_key: Optional[str] = None
    zotero_attachment_key: Optional[str] = None
    zotero_target_id: Optional[str] = None
    reading_mode: str = "legacy"


@dataclass
class PipelineResult:
    citekey: str
    zotero_item_key: str
    zotero_attachment_key: str
    packet_path: Path
    analysis_path: Path
    note_path: Optional[Path]
    obsidian_target: str
    reading_mode: str = "legacy"
    skim_path: Optional[Path] = None
    deep_read_path: Optional[Path] = None
    discussion_path: Optional[Path] = None


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return cleaned or "paper"


def generate_citekey(authors: List[str], year: Optional[str], title: str) -> str:
    first_author = authors[0] if authors else "paper"
    surname = first_author.split()[-1].lower()
    year_part = year or "nd"
    keyword = _slug(title).split("-")[0] or "paper"
    return f"{surname}{year_part}{keyword}"


def packet_path_for_pdf(pdf_path: Path, config: AppConfig) -> Path:
    if config.packet_dir:
        return Path(config.packet_dir) / f"{pdf_path.stem}.paper.json"
    return pdf_path.with_suffix(".paper.json")


def analysis_path_for_packet(packet_path: Path) -> Path:
    return packet_path.with_suffix(".analysis.json")


def note_path_for_paper(paper: PaperPacket, config: AppConfig) -> Optional[Path]:
    if config.obsidian_vault_path:
        return Path(config.obsidian_vault_path) / config.note_subdir / paper.note_relative_path().name
    return None


def obsidian_relative_path(paper: PaperPacket, config: AppConfig) -> str:
    return (Path(config.note_subdir) / paper.note_relative_path().name).as_posix()


def extract_prefill(pdf_path: Path) -> IngestRequest:
    metadata = extract_pdf_metadata(pdf_path)
    return IngestRequest(
        pdf_path=pdf_path,
        title=str(metadata["title"]),
        authors=[str(author) for author in metadata["authors"]],
        year=metadata["year"] and str(metadata["year"]),
        journal=metadata["journal"] and str(metadata["journal"]),
        doi=metadata["doi"] and str(metadata["doi"]),
        url=metadata["url"] and str(metadata["url"]),
        abstract=metadata["abstract"] and str(metadata["abstract"]),
    )


def _progress(callback: ProgressCallback, message: str) -> None:
    if callback:
        callback(message)


def run_ingest_pipeline(
    request: IngestRequest,
    config: AppConfig,
    *,
    progress: ProgressCallback = None,
) -> PipelineResult:
    config.validate()
    config.require_zotero()
    config.require_llm()

    pdf_path = request.pdf_path.expanduser().resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    citekey = generate_citekey(request.authors, request.year, request.title)
    zotero_attachment_key = request.zotero_attachment_key or ""
    if request.zotero_item_key:
        _progress(progress, "Using the Zotero item that was already recognized from Zotero Desktop...")
        zotero_item_key = request.zotero_item_key
    else:
        _progress(progress, "Creating Zotero item and uploading PDF...")
        zotero = ZoteroClient(config)
        zotero_result = zotero.create_item_with_pdf(
            item_type=request.item_type,
            title=request.title,
            authors=request.authors,
            year=request.year,
            journal=request.journal,
            doi=request.doi,
            url=request.url,
            abstract=request.abstract,
            tags=request.tags or [],
            citekey=citekey,
            pdf_path=pdf_path,
        )
        zotero_item_key = zotero_result["parent_key"]
        zotero_attachment_key = zotero_result["attachment_key"]

    packet = PaperPacket(
        citekey=citekey,
        zotero_item_key=zotero_item_key,
        title=request.title,
        authors=request.authors,
        year=request.year,
        journal=request.journal,
        doi=request.doi,
        url=request.url,
        abstract=request.abstract,
        annotation_text=request.annotation_text,
        pdf_path=str(pdf_path),
        tags=request.tags or [],
        status=request.status,
    )

    packet_path = packet_path_for_pdf(pdf_path, config)
    analysis_path = analysis_path_for_packet(packet_path)
    _progress(progress, f"Saving packet to {packet_path}...")
    save_json(packet_path, packet.source_summary())

    reading_mode = request.reading_mode
    skim_path = None
    deep_read_path = None
    discussion_path = None

    if reading_mode == "three-phase":
        from .agents import run_full_reading
        from .text_extraction import extract_and_segment

        sections = None
        try:
            _progress(progress, "Extracting full text from PDF for section-level analysis...")
            sections = extract_and_segment(pdf_path)
            section_keys = [k for k in sections if k != "full_text"]
            _progress(progress, f"Extracted sections: {', '.join(section_keys)}")
        except RuntimeError:
            _progress(progress, "Full text extraction unavailable, proceeding with metadata only...")

        skim, deep_read, discussion = run_full_reading(
            packet, config, sections=sections, progress=progress,
        )

        skim_path = packet_path.with_suffix(".skim.json")
        deep_read_path = packet_path.with_suffix(".deep-read.json")
        discussion_path = packet_path.with_suffix(".discussion.json")
        save_json(skim_path, skim.to_dict())
        save_json(deep_read_path, deep_read.to_dict())
        save_json(discussion_path, discussion.to_dict())

        # Also save a combined analysis for compatibility
        analysis_dict = {
            "skim": skim.to_dict(),
            "deep_read": deep_read.to_dict(),
            "discussion": discussion.to_dict(),
        }
        save_json(analysis_path, analysis_dict)

        note_markdown = render_full_note(packet, skim, deep_read, discussion)
    else:
        _progress(progress, f"Sending packet to {config.active_llm_label()} for structured analysis...")
        analysis_dict = create_analysis_for_config(packet, config)
        analysis = AnalysisPacket.from_dict(analysis_dict)
        save_json(analysis_path, analysis_dict)
        note_markdown = render_note(packet, analysis)
    note_path = note_path_for_paper(packet, config)
    obsidian_target = obsidian_relative_path(packet, config)
    if config.obsidian_rest_url and config.obsidian_rest_api_key:
        _progress(progress, f"Writing note into Obsidian via REST at {obsidian_target}...")
        write_note(config.obsidian_rest_url, config.obsidian_rest_api_key, obsidian_target, note_markdown)
    elif note_path:
        _progress(progress, f"Writing note into vault at {note_path}...")
        save_text(note_path, note_markdown)
    else:
        fallback_note = packet_path.parent / config.note_subdir / packet.note_relative_path().name
        _progress(progress, f"No Obsidian target configured. Writing note to {fallback_note}...")
        save_text(fallback_note, note_markdown)
        note_path = fallback_note

    _progress(progress, "Pipeline complete.")
    return PipelineResult(
        citekey=citekey,
        zotero_item_key=zotero_item_key,
        zotero_attachment_key=zotero_attachment_key,
        packet_path=packet_path,
        analysis_path=analysis_path,
        note_path=note_path,
        obsidian_target=obsidian_target,
        reading_mode=reading_mode,
        skim_path=skim_path,
        deep_read_path=deep_read_path,
        discussion_path=discussion_path,
    )
