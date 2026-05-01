from __future__ import annotations

import json
from typing import Dict

from .models import PaperPacket
from .schemas import analysis_schema


NO_EVIDENCE_FALLBACK = "Not enough evidence in source packet."


def build_analysis_payload(paper: PaperPacket) -> Dict[str, object]:
    payload = paper.source_summary()
    if paper.annotations:
        payload["annotation_blocks"] = [item.to_display_block() for item in paper.annotations]
    return payload


def build_prompt(paper: PaperPacket) -> str:
    payload = build_analysis_payload(paper)
    schema = analysis_schema()
    packet_json = json.dumps(payload, indent=2, ensure_ascii=False)
    schema_json = json.dumps(schema, indent=2, ensure_ascii=False)
    return f"""# Research Note Generation Task

You are a meticulous research synthesis assistant producing an Obsidian-ready literature note from one Zotero-derived paper packet.

## Mission
Create a faithful, reusable, Chinese-first bilingual note that helps a future reader recover:
- what the paper is about
- how it works
- what it found
- why it matters
- where its limits are
- what to do next in the vault

## Hard constraints
- Use only evidence contained in the source packet below.
- Never invent methods, datasets, results, numbers, claims, or quotations.
- If a field lacks support, say `{NO_EVIDENCE_FALLBACK}` rather than guessing.
- Keep the main narrative in Chinese, but preserve important English technical terms, benchmark names, model names, and quoted phrases when they matter.
- Keep source-grounded analysis separate from reader-oriented reflection.
- Return JSON only.
- The JSON must match the schema exactly, with no extra keys and no markdown fences.

## Intended final note shape
The JSON will later be rendered into an Obsidian literature note with:
- YAML frontmatter for citation metadata
- an at-a-glance bibliographic snapshot
- sections for summary, question, methods, findings, strengths, limitations, quotes, connections, and next actions

## Field-by-field writing instructions
- `chinese_summary`: one dense but readable Chinese paragraph, focused on the paper's actual contribution and result.
- `english_abstract_snapshot`: 2 to 4 English sentences that preserve the paper's original framing and terminology.
- `core_question`: one sentence stating the central research problem the paper tries to solve.
- `methods`: concrete method steps, design choices, datasets, or evaluation setup when present. Avoid vague topic labels.
- `key_findings`: actual reported findings or conclusions, not generic restatements of the topic.
- `strengths`: evidence-based reasons the paper is useful, careful, interesting, or well-designed.
- `limitations`: real caveats, uncertainty, boundary conditions, or missing evidence. Avoid generic criticism.
- `useful_quotes`: only direct quotations that already appear in the packet. If there are no direct quotes, return an empty list.
- `my_connections`: concise links to adjacent ideas, theories, projects, or reading paths that would help a knowledge vault user. Use `[[wikilink]]` format for each concept or paper name (e.g. `[[Transformer]]`, `[[RAG]]`).
- `next_actions`: actionable follow-up steps for reading, comparison, note-linking, replication, or open questions.
- `suggested_tags`: 3-8 short lowercase kebab-case tags classifying the paper's domain, method family, and task type (e.g. `graph-neural-network`, `retrieval-augmented-generation`). Do not repeat generic tags like `paper` or `research`.
- `key_concepts`: 5-15 key concept, method, model, or dataset names that appear in this paper. Use canonical English names (e.g. `Transformer`, `GNN`, `LoRA`). No brackets — they will be wrapped in `[[]]` automatically.

## Quality checklist
Before returning, verify that:
- methods are not mixed with findings
- limitations are evidence-based rather than boilerplate
- quoted text is verbatim from the packet
- every claim is grounded in the packet
- empty or weakly supported fields use `{NO_EVIDENCE_FALLBACK}` or an empty quote list where appropriate

## Output schema
```json
{schema_json}
```

## Source packet
```json
{packet_json}
```
"""
