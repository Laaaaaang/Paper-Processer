from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .config import AppConfig
from .io_utils import load_json, save_json, save_text
from .llm_client import (
    LLMResponseError,
    create_analysis_for_provider,
    default_model_for_provider,
)
from .models import AnalysisPacket, DeepReadResult, DiscussionResult, PaperPacket, SkimResult
from .obsidian import ObsidianWriteError, write_note
from .pipeline import IngestRequest, extract_prefill, run_ingest_pipeline
from .prompting import build_prompt
from .rendering import render_full_note, render_note
from .schemas import analysis_schema
from .webapp import launch_web_app


def _load_paper(path: Path) -> PaperPacket:
    paper = PaperPacket.from_dict(load_json(path))
    paper.validate()
    return paper


def _load_analysis(path: Path) -> AnalysisPacket:
    return AnalysisPacket.from_dict(load_json(path))


def _default_output_path(output_dir: Path, paper: PaperPacket) -> Path:
    return output_dir / paper.note_relative_path()


def cmd_validate(args: argparse.Namespace) -> int:
    paper = _load_paper(Path(args.input))
    print(json.dumps(paper.source_summary(), indent=2, ensure_ascii=False))
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    schema_json = json.dumps(analysis_schema(), indent=2, ensure_ascii=False) + "\n"
    if args.output:
        save_text(Path(args.output), schema_json)
    else:
        sys.stdout.write(schema_json)
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    paper = _load_paper(Path(args.input))
    prompt = build_prompt(paper)
    if args.output:
        save_text(Path(args.output), prompt)
    else:
        sys.stdout.write(prompt)
    return 0


def _save_note_and_analysis(
    paper: PaperPacket,
    analysis_dict,
    note_output: Path,
    analysis_output: Optional[Path],
) -> str:
    analysis = AnalysisPacket.from_dict(analysis_dict)
    note_markdown = render_note(paper, analysis)
    save_text(note_output, note_markdown)
    if analysis_output:
        save_json(analysis_output, analysis_dict)
    return note_markdown


def _obsidian_target_path(paper: PaperPacket) -> str:
    return paper.note_relative_path().as_posix()


def cmd_finalize(args: argparse.Namespace) -> int:
    paper = _load_paper(Path(args.input))
    analysis = _load_analysis(Path(args.analysis))
    note_markdown = render_note(paper, analysis)

    if args.obsidian_url and args.obsidian_api_key:
        try:
            write_note(
                args.obsidian_url,
                args.obsidian_api_key,
                _obsidian_target_path(paper),
                note_markdown,
            )
        except ObsidianWriteError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(_obsidian_target_path(paper))
        return 0

    output_dir = Path(args.output_dir)
    output_path = _default_output_path(output_dir, paper)
    save_text(output_path, note_markdown)
    print(output_path)
    return 0


def cmd_synthesize(args: argparse.Namespace) -> int:
    paper = _load_paper(Path(args.input))
    try:
        analysis_dict = create_analysis_for_provider(
            paper,
            provider=args.provider,
            model=args.model or default_model_for_provider(args.provider),
            api_key=args.api_key,
        )
    except LLMResponseError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    analysis_output = (
        Path(args.analysis_output)
        if args.analysis_output
        else Path(args.output_dir) / "analysis" / f"{paper.citekey}.analysis.json"
    )

    note_output = _default_output_path(Path(args.output_dir), paper)
    note_markdown = _save_note_and_analysis(
        paper,
        analysis_dict,
        note_output=note_output,
        analysis_output=analysis_output,
    )

    if args.obsidian_url and args.obsidian_api_key:
        try:
            write_note(
                args.obsidian_url,
                args.obsidian_api_key,
                _obsidian_target_path(paper),
                note_markdown,
            )
        except ObsidianWriteError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    print(note_output)
    return 0


def _load_config(path_value: str) -> AppConfig:
    return AppConfig.from_path(Path(path_value))


def cmd_from_pdf(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf).expanduser().resolve()
    request = extract_prefill(pdf_path)
    paper = {
        "pdf_path": str(pdf_path),
        "title": request.title,
        "authors": request.authors,
        "year": request.year,
        "url": request.url,
    }
    sys.stdout.write(json.dumps(paper, indent=2, ensure_ascii=False) + "\n")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    pdf_path = Path(args.pdf).expanduser().resolve()
    request = IngestRequest(
        pdf_path=pdf_path,
        title=args.title,
        authors=[item.strip() for item in args.authors.split(",") if item.strip()],
        year=args.year,
        journal=args.journal,
        doi=args.doi,
        url=args.url,
        abstract=args.abstract,
        annotation_text=args.annotation_text,
        tags=[item.strip() for item in (args.tags or "").split(",") if item.strip()],
        status=args.status or config.default_status,
        item_type=args.item_type or config.default_item_type,
    )

    result = run_ingest_pipeline(
        request,
        config,
        progress=lambda message: print(message, file=sys.stderr),
    )
    output = {
        "citekey": result.citekey,
        "zotero_item_key": result.zotero_item_key,
        "zotero_attachment_key": result.zotero_attachment_key,
        "packet_path": str(result.packet_path),
        "analysis_path": str(result.analysis_path),
        "note_path": str(result.note_path) if result.note_path else None,
        "obsidian_target": result.obsidian_target,
    }
    sys.stdout.write(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    launch_web_app(
        host=args.host,
        port=args.port,
        config_path=Path(args.config),
        open_browser=not args.no_browser,
    )
    return 0


# ---------------------------------------------------------------------------
# Three-phase reading commands
# ---------------------------------------------------------------------------


def _load_sections(paper: PaperPacket) -> dict | None:
    """Try to load or extract text sections from the paper's PDF."""
    from .text_extraction import extract_and_segment, load_extracted_sections

    if paper.extracted_text_path:
        path = Path(paper.extracted_text_path)
        if path.exists():
            return load_extracted_sections(path)

    if paper.pdf_path:
        pdf = Path(paper.pdf_path)
        if pdf.exists():
            try:
                return extract_and_segment(pdf)
            except RuntimeError:
                pass
    return None


def cmd_skim(args: argparse.Namespace) -> int:
    from .agents import run_skim_agent

    config = _load_config(args.config)
    paper = _load_paper(Path(args.input))
    sections = _load_sections(paper)
    try:
        skim = run_skim_agent(paper, config, sections=sections)
    except LLMResponseError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    output_path = Path(args.output) if args.output else Path(args.input).with_suffix(".skim.json")
    save_json(output_path, skim.to_dict())
    print(output_path)
    return 0


def cmd_deep_read(args: argparse.Namespace) -> int:
    from .agents import run_deep_read_agent

    config = _load_config(args.config)
    paper = _load_paper(Path(args.input))
    sections = _load_sections(paper)
    skim = None
    if args.skim_input:
        skim = SkimResult.from_dict(load_json(Path(args.skim_input)))
    try:
        deep_read = run_deep_read_agent(paper, config, skim=skim, sections=sections)
    except LLMResponseError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    output_path = (
        Path(args.output) if args.output else Path(args.input).with_suffix(".deep-read.json")
    )
    save_json(output_path, deep_read.to_dict())
    print(output_path)
    return 0


def cmd_discuss(args: argparse.Namespace) -> int:
    from .agents import run_discussion_agent

    config = _load_config(args.config)
    paper = _load_paper(Path(args.input))
    sections = _load_sections(paper)
    skim = None
    deep_read = None
    if args.skim_input:
        skim = SkimResult.from_dict(load_json(Path(args.skim_input)))
    if args.deep_read_input:
        deep_read = DeepReadResult.from_dict(load_json(Path(args.deep_read_input)))
    try:
        discussion = run_discussion_agent(
            paper, config, skim=skim, deep_read=deep_read, sections=sections
        )
    except LLMResponseError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    output_path = (
        Path(args.output) if args.output else Path(args.input).with_suffix(".discussion.json")
    )
    save_json(output_path, discussion.to_dict())
    print(output_path)
    return 0


def cmd_full_read(args: argparse.Namespace) -> int:
    from .agents import run_full_reading

    config = _load_config(args.config)
    paper = _load_paper(Path(args.input))
    sections = _load_sections(paper)
    base = Path(args.input).with_suffix("")
    try:
        skim, deep_read, discussion = run_full_reading(
            paper,
            config,
            sections=sections,
            progress=lambda msg: print(msg, file=sys.stderr),
        )
    except LLMResponseError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    skim_path = Path(f"{base}.skim.json")
    deep_read_path = Path(f"{base}.deep-read.json")
    discussion_path = Path(f"{base}.discussion.json")
    save_json(skim_path, skim.to_dict())
    save_json(deep_read_path, deep_read.to_dict())
    save_json(discussion_path, discussion.to_dict())

    output_dir = Path(args.output_dir)
    note_path = output_dir / paper.note_relative_path()
    note_markdown = render_full_note(paper, skim, deep_read, discussion)
    save_text(note_path, note_markdown)
    print(note_path)
    return 0


def cmd_extract_text(args: argparse.Namespace) -> int:
    from .text_extraction import extract_and_segment, save_extracted_sections

    pdf_path = Path(args.pdf).expanduser().resolve()
    sections = extract_and_segment(pdf_path)
    output_path = (
        Path(args.output) if args.output else pdf_path.with_suffix(".sections.json")
    )
    save_extracted_sections(sections, output_path)
    section_keys = [k for k in sections if k != "full_text"]
    print(f"Extracted {len(section_keys)} sections: {', '.join(section_keys)}")
    print(output_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-flow",
        description="Thin glue for a Zotero -> Codex -> Obsidian literature-note workflow.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate a normalized paper packet.")
    validate_parser.add_argument("input", help="Path to a normalized paper JSON file.")
    validate_parser.set_defaults(func=cmd_validate)

    schema_parser = subparsers.add_parser(
        "schema", help="Print or save the required JSON schema for AI analysis output."
    )
    schema_parser.add_argument("--output", help="Optional path to save the schema JSON.")
    schema_parser.set_defaults(func=cmd_schema)

    prepare_parser = subparsers.add_parser(
        "prepare", help="Generate the reusable synthesis prompt for a paper packet."
    )
    prepare_parser.add_argument("input", help="Path to a normalized paper JSON file.")
    prepare_parser.add_argument(
        "--output", help="Optional path to save the generated prompt Markdown."
    )
    prepare_parser.set_defaults(func=cmd_prepare)

    finalize_parser = subparsers.add_parser(
        "finalize", help="Render an Obsidian note from a paper packet and analysis JSON."
    )
    finalize_parser.add_argument("input", help="Path to a normalized paper JSON file.")
    finalize_parser.add_argument("analysis", help="Path to the structured analysis JSON file.")
    finalize_parser.add_argument(
        "--output-dir",
        default="generated",
        help="Directory to write the note into when not using Obsidian REST API.",
    )
    finalize_parser.add_argument("--obsidian-url", help="Obsidian Local REST API base URL.")
    finalize_parser.add_argument("--obsidian-api-key", help="Obsidian Local REST API key.")
    finalize_parser.set_defaults(func=cmd_finalize)

    synthesize_parser = subparsers.add_parser(
        "synthesize",
        help="Call the configured LLM API, save the structured analysis, and render the note.",
    )
    synthesize_parser.add_argument("input", help="Path to a normalized paper JSON file.")
    synthesize_parser.add_argument(
        "--provider",
        choices=["openai", "gemini"],
        default="openai",
        help="LLM provider to call. Defaults to openai.",
    )
    synthesize_parser.add_argument(
        "--model",
        help="Model name for note synthesis. Defaults to the provider's standard model.",
    )
    synthesize_parser.add_argument(
        "--api-key",
        help="Provider API key. Falls back to OPENAI_API_KEY for OpenAI or GEMINI_API_KEY / GOOGLE_API_KEY for Gemini.",
    )
    synthesize_parser.add_argument(
        "--output-dir",
        default="generated",
        help="Directory to write analysis and note outputs.",
    )
    synthesize_parser.add_argument(
        "--analysis-output",
        help="Optional path for the saved structured analysis JSON output.",
    )
    synthesize_parser.add_argument("--obsidian-url", help="Obsidian Local REST API base URL.")
    synthesize_parser.add_argument("--obsidian-api-key", help="Obsidian Local REST API key.")
    synthesize_parser.set_defaults(func=cmd_synthesize)

    from_pdf_parser = subparsers.add_parser(
        "from-pdf",
        help="Extract best-effort metadata from a PDF path for GUI or packet prefill.",
    )
    from_pdf_parser.add_argument("pdf", help="Path to a PDF file.")
    from_pdf_parser.set_defaults(func=cmd_from_pdf)

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Run the automated PDF -> Zotero -> packet -> LLM -> Obsidian pipeline.",
    )
    ingest_parser.add_argument("pdf", help="Path to the PDF file.")
    ingest_parser.add_argument("--config", default="research-flow.config.json", help="Path to the config JSON file.")
    ingest_parser.add_argument("--title", required=True, help="Paper title.")
    ingest_parser.add_argument("--authors", required=True, help="Comma-separated authors.")
    ingest_parser.add_argument("--year", help="Publication year.")
    ingest_parser.add_argument("--journal", help="Journal or venue.")
    ingest_parser.add_argument("--doi", help="DOI.")
    ingest_parser.add_argument("--url", help="Canonical URL.")
    ingest_parser.add_argument("--abstract", help="Abstract text.")
    ingest_parser.add_argument("--annotation-text", help="Summary of highlights or notes.")
    ingest_parser.add_argument("--tags", help="Comma-separated tags.")
    ingest_parser.add_argument("--status", help="Frontmatter status.")
    ingest_parser.add_argument("--item-type", help="Zotero item type, e.g. journalArticle.")
    ingest_parser.set_defaults(func=cmd_ingest)

    # -----------------------------------------------------------------------
    # Three-phase reading commands
    # -----------------------------------------------------------------------

    _config_arg = {"default": "research-flow.config.json", "help": "Path to config JSON."}

    skim_parser = subparsers.add_parser(
        "skim",
        help="Phase 1: Quick read of abstract + conclusion.",
    )
    skim_parser.add_argument("input", help="Path to a normalized paper JSON file.")
    skim_parser.add_argument("--config", **_config_arg)
    skim_parser.add_argument("--output", help="Path to save skim result JSON.")
    skim_parser.set_defaults(func=cmd_skim)

    deep_read_parser = subparsers.add_parser(
        "deep-read",
        help="Phase 2: Close reading of methods and algorithms.",
    )
    deep_read_parser.add_argument("input", help="Path to a normalized paper JSON file.")
    deep_read_parser.add_argument("--config", **_config_arg)
    deep_read_parser.add_argument(
        "--skim-input", help="Path to a skim result JSON (from Phase 1) for context."
    )
    deep_read_parser.add_argument("--output", help="Path to save deep-read result JSON.")
    deep_read_parser.set_defaults(func=cmd_deep_read)

    discuss_parser = subparsers.add_parser(
        "discuss",
        help="Phase 3: Experimental evaluation, limitations, and future directions.",
    )
    discuss_parser.add_argument("input", help="Path to a normalized paper JSON file.")
    discuss_parser.add_argument("--config", **_config_arg)
    discuss_parser.add_argument(
        "--skim-input", help="Path to skim result JSON for context."
    )
    discuss_parser.add_argument(
        "--deep-read-input", help="Path to deep-read result JSON for context."
    )
    discuss_parser.add_argument("--output", help="Path to save discussion result JSON.")
    discuss_parser.set_defaults(func=cmd_discuss)

    full_read_parser = subparsers.add_parser(
        "full-read",
        help="Run all three reading phases sequentially and render a combined note.",
    )
    full_read_parser.add_argument("input", help="Path to a normalized paper JSON file.")
    full_read_parser.add_argument("--config", **_config_arg)
    full_read_parser.add_argument(
        "--output-dir", default="generated", help="Directory for the rendered note."
    )
    full_read_parser.set_defaults(func=cmd_full_read)

    extract_text_parser = subparsers.add_parser(
        "extract-text",
        help="Extract full text from a PDF and segment into paper sections.",
    )
    extract_text_parser.add_argument("pdf", help="Path to a PDF file.")
    extract_text_parser.add_argument("--output", help="Path to save extracted sections JSON.")
    extract_text_parser.set_defaults(func=cmd_extract_text)

    gui_parser = subparsers.add_parser(
        "gui",
        help="Launch the local browser UI. This replaces the unstable macOS Tk window.",
    )
    gui_parser.add_argument(
        "--config",
        default="research-flow.config.json",
        help="Path to the config JSON file.",
    )
    gui_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface for the local web UI.",
    )
    gui_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Preferred port for the local web UI.",
    )
    gui_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the local web UI without opening a browser automatically.",
    )
    gui_parser.set_defaults(func=cmd_gui)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
