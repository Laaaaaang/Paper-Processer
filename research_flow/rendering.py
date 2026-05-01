from __future__ import annotations

import json
from typing import Iterable, List, Optional

from .models import (
    AnalysisPacket,
    DeepReadResult,
    DiscussionResult,
    PaperPacket,
    SkimResult,
)


NO_EVIDENCE_FALLBACK = "Not enough evidence in source packet."


def _yaml_value(value: object) -> str:
    if value is None:
        return '""'
    if isinstance(value, list):
        return _yaml_list(value)
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _yaml_list(items: list) -> str:
    """Render a list as a YAML block sequence (Obsidian / Dataview compatible)."""
    if not items:
        return "[]"
    return "\n" + "\n".join(f"  - {json.dumps(str(i), ensure_ascii=False)}" for i in items)


def _merge_tags(zotero_tags: List[str], llm_tags: List[str]) -> List[str]:
    """Merge Zotero-sourced tags with LLM-suggested tags, deduplicated, stable order."""
    seen: set = set()
    merged: List[str] = []
    for tag in list(zotero_tags) + list(llm_tags) + ["literature-note"]:
        normalized = tag.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            merged.append(tag.strip())
    return merged


def _concept_links(concepts: List[str]) -> str:
    """Render concepts as a line of [[wiki-links]] separated by ·."""
    if not concepts:
        return f"- {NO_EVIDENCE_FALLBACK}"
    return " · ".join(f"[[{c.strip()}]]" for c in concepts if c.strip())


def _bullet_list(items: Iterable[str]) -> str:
    lines = [f"- {item}" for item in items]
    return "\n".join(lines) if lines else f"- {NO_EVIDENCE_FALLBACK}"


def _display_text(value: object, fallback: str = "Unknown") -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(cleaned) if cleaned else fallback
    cleaned = str(value).strip()
    return cleaned or fallback


def _callout_block(lines: Iterable[str]) -> str:
    return "\n".join(f"> {line}" for line in lines)


def render_note(paper: PaperPacket, analysis: AnalysisPacket) -> str:
    merged_tags = _merge_tags(paper.tags, analysis.suggested_tags)
    frontmatter = [
        "---",
        f"citekey: {_yaml_value(paper.citekey)}",
        f"zotero_key: {_yaml_value(paper.zotero_item_key)}",
        f"title: {_yaml_value(paper.title)}",
        f"authors: {_yaml_value(paper.authors)}",
        f"year: {_yaml_value(paper.year)}",
        f"journal: {_yaml_value(paper.journal)}",
        f"doi: {_yaml_value(paper.doi)}",
        f"url: {_yaml_value(paper.url)}",
        f"tags: {_yaml_value(merged_tags)}",
        f"concepts: {_yaml_value(analysis.key_concepts)}",
        f"status: {_yaml_value(paper.status)}",
        f"note_type: {_yaml_value('literature-note')}",
        f"generated_by: {_yaml_value('research_flow')}",
        f"source_pdf: {_yaml_value(paper.pdf_path)}",
        "---",
        "",
    ]

    quote_blocks: List[str] = []
    if analysis.useful_quotes:
        for quote in analysis.useful_quotes:
            page_suffix = f" (p. {quote.page_label})" if quote.page_label else ""
            quote_blocks.append(
                f"> {quote.quote}\n>\n> Why it matters: {quote.why_it_matters}{page_suffix}"
            )
    else:
        quote_blocks.append("- No direct quotes were available in the source packet.")

    snapshot_lines = [
        "[!summary] At a Glance",
        f"- Authors: {_display_text(paper.authors)}",
        f"- Year: {_display_text(paper.year)}",
        f"- Venue: {_display_text(paper.journal)}",
        f"- DOI: {_display_text(paper.doi, fallback='Not provided')}",
        f"- Citekey: {_display_text(paper.citekey)}",
        f"- Zotero item: {_display_text(paper.zotero_item_key)}",
    ]
    if paper.url:
        snapshot_lines.append(f"- Source URL: {paper.url}")

    provenance = [
        f"Citekey: `{paper.citekey}`",
        f"Zotero item key: `{paper.zotero_item_key}`",
        f"Status: `{paper.status}`",
    ]
    if paper.annotation_text:
        provenance.append("Annotations imported from Zotero.")
    if paper.annotations:
        provenance.append(f"{len(paper.annotations)} structured annotations available.")
    if paper.pdf_path:
        provenance.append(f"PDF path: `{paper.pdf_path}`")
    if paper.extracted_text_path:
        provenance.append(f"Extracted text path: `{paper.extracted_text_path}`")
    if not paper.annotation_text and not paper.annotations:
        provenance.append("No Zotero annotations were included in the source packet.")

    body = [
        f"# {paper.title}",
        "",
        _callout_block(snapshot_lines),
        "",
        "## 中文摘要",
        analysis.chinese_summary,
        "",
        "## English Abstract Snapshot",
        analysis.english_abstract_snapshot,
        "",
        "## Core Question",
        analysis.core_question,
        "",
        "## Methods",
        _bullet_list(analysis.methods),
        "",
        "## Key Findings",
        _bullet_list(analysis.key_findings),
        "",
        "## Strengths",
        _bullet_list(analysis.strengths),
        "",
        "## Limitations",
        _bullet_list(analysis.limitations),
        "",
        "## Useful Quotes",
        "\n\n".join(quote_blocks),
        "",
        "## Key Concepts",
        _concept_links(analysis.key_concepts),
        "",
        "## My Connections",
        _bullet_list(analysis.my_connections),
        "",
        "## Next Actions",
        _bullet_list(analysis.next_actions),
        "",
        "## Provenance",
        _bullet_list(provenance),
        "",
    ]
    return "\n".join(frontmatter + body)


# ---------------------------------------------------------------------------
# Three-phase rendering
# ---------------------------------------------------------------------------


def _render_algorithm_steps(deep_read: DeepReadResult) -> str:
    """Render algorithm steps as a numbered list with details."""
    if not deep_read.algorithm_steps:
        return f"- {NO_EVIDENCE_FALLBACK}"
    blocks: List[str] = []
    for idx, step in enumerate(deep_read.algorithm_steps, 1):
        lines = [f"### Step {idx}: {step.step_name}", "", step.description, ""]
        lines.append(f"- **Inputs**: {step.inputs}")
        lines.append(f"- **Outputs**: {step.outputs}")
        if step.formulas:
            lines.append(f"- **Formulas**: ${step.formulas}$")
        if step.why_it_matters:
            lines.append(f"- **Why it matters**: {step.why_it_matters}")
        lines.append("")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _render_results_table(discussion: DiscussionResult) -> str:
    """Render quantitative results as a markdown table."""
    if not discussion.quantitative_results:
        return f"- {NO_EVIDENCE_FALLBACK}"
    lines = [
        "| Metric | Value | vs. Baseline | Interpretation |",
        "|--------|-------|-------------|----------------|",
    ]
    for r in discussion.quantitative_results:
        lines.append(f"| {r.metric} | {r.value} | {r.comparison} | {r.interpretation} |")
    return "\n".join(lines)


def render_full_note(
    paper: PaperPacket,
    skim: SkimResult,
    deep_read: DeepReadResult,
    discussion: DiscussionResult,
) -> str:
    """Render a complete literature note from three-phase reading results."""
    merged_tags = _merge_tags(paper.tags, skim.suggested_tags)
    frontmatter = [
        "---",
        f"citekey: {_yaml_value(paper.citekey)}",
        f"zotero_key: {_yaml_value(paper.zotero_item_key)}",
        f"title: {_yaml_value(paper.title)}",
        f"authors: {_yaml_value(paper.authors)}",
        f"year: {_yaml_value(paper.year)}",
        f"journal: {_yaml_value(paper.journal)}",
        f"doi: {_yaml_value(paper.doi)}",
        f"url: {_yaml_value(paper.url)}",
        f"tags: {_yaml_value(merged_tags)}",
        f"concepts: {_yaml_value(skim.key_concepts)}",
        f"status: {_yaml_value(paper.status)}",
        f"note_type: {_yaml_value('literature-note')}",
        f"generated_by: {_yaml_value('research_flow')}",
        f"reading_mode: {_yaml_value('three-phase')}",
        f"research_type: {_yaml_value(skim.research_type)}",
        f"reading_priority: {_yaml_value(skim.reading_priority)}",
        f"source_pdf: {_yaml_value(paper.pdf_path)}",
        "---",
        "",
    ]

    snapshot_lines = [
        "[!summary] At a Glance",
        f"- Authors: {_display_text(paper.authors)}",
        f"- Year: {_display_text(paper.year)}",
        f"- Venue: {_display_text(paper.journal)}",
        f"- DOI: {_display_text(paper.doi, fallback='Not provided')}",
        f"- Research type: {skim.research_type}",
        f"- Reading priority: {skim.reading_priority}",
        f"- Citekey: {_display_text(paper.citekey)}",
    ]
    if paper.url:
        snapshot_lines.append(f"- Source URL: {paper.url}")

    provenance = [
        f"Citekey: `{paper.citekey}`",
        f"Zotero item key: `{paper.zotero_item_key}`",
        f"Status: `{paper.status}`",
        "Reading mode: three-phase (skim → deep-read → discussion)",
    ]
    if paper.pdf_path:
        provenance.append(f"PDF path: `{paper.pdf_path}`")

    body = [
        f"# {paper.title}",
        "",
        _callout_block(snapshot_lines),
        "",
        "---",
        "",
        "# Phase 1: 粗读 (Skim)",
        "",
        "## Core Question",
        skim.core_question,
        "",
        "## TL;DR 摘要",
        skim.tldr_abstract,
        "",
        "## Conclusion Takeaways",
        _bullet_list(skim.conclusion_takeaways),
        "",
        "## Initial Impression",
        skim.initial_impression,
        "",
        "## Key Concepts",
        _concept_links(skim.key_concepts),
        "",
        "---",
        "",
        "# Phase 2: 精读 Methods & Algorithms",
        "",
        "## 算法总览",
        deep_read.algorithm_overview,
        "",
        "## 算法流程拆解",
        _render_algorithm_steps(deep_read),
        "",
        "## Key Design Choices",
        _bullet_list(deep_read.key_design_choices),
        "",
        "## 技术新颖性",
        _bullet_list(deep_read.technical_novelty),
        "",
        "## Implementation Details",
        _bullet_list(deep_read.implementation_details),
        "",
        "## 🔍 Open Questions (苏格拉底式追问)",
        _bullet_list(deep_read.open_questions_for_reader),
        "",
        "---",
        "",
        "# Phase 3: 讨论与批判",
        "",
        "## Experimental Setup",
        discussion.experimental_setup,
        "",
        "## Baselines",
        _bullet_list(discussion.baselines),
        "",
        "## 定量结果",
        _render_results_table(discussion),
        "",
        "## 局限性分析",
        _bullet_list(discussion.limitations_analysis),
        "",
        "## Future Directions",
        _bullet_list(discussion.future_directions),
        "",
        "## 我的批判性评价",
        discussion.my_critique,
        "",
        "## Vault Connections",
        _bullet_list(discussion.connections_to_vault),
        "",
        "---",
        "",
        "## Provenance",
        _bullet_list(provenance),
        "",
    ]
    return "\n".join(frontmatter + body)
