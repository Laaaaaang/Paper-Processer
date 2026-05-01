"""Three-phase reading agents: skim, deep-read, discussion.

Each agent can run independently or as part of a sequential pipeline.
Later agents produce better results when given prior phase outputs as context.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from .models import DeepReadResult, DiscussionResult, PaperPacket, SkimResult
from .schemas import deep_read_schema, discussion_schema, skim_schema


NO_EVIDENCE_FALLBACK = "Not enough evidence in source packet."


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------


def _base_payload(paper: PaperPacket) -> Dict[str, object]:
    payload = paper.source_summary()
    if paper.annotations:
        payload["annotation_blocks"] = [item.to_display_block() for item in paper.annotations]
    return payload


def _section_payload(
    paper: PaperPacket,
    sections: Optional[Dict[str, str]] = None,
    *,
    keys: Optional[list[str]] = None,
) -> Dict[str, object]:
    """Build payload with optional extracted text sections.

    If *sections* is provided (from text_extraction), only include the
    *keys* requested.  Otherwise fall back to the base payload.
    """
    payload = _base_payload(paper)
    if sections and keys:
        payload["extracted_sections"] = {k: sections[k] for k in keys if k in sections}
    return payload


# ---------------------------------------------------------------------------
# Shared constraints block (DRY across all three prompts)
# ---------------------------------------------------------------------------

_HARD_CONSTRAINTS = f"""\
## Hard constraints
- Use only evidence contained in the source packet below.
- Never invent methods, datasets, results, numbers, claims, or quotations.
- If a field lacks support, write `{NO_EVIDENCE_FALLBACK}` rather than guessing.
- Keep the main narrative in Chinese. Preserve key English technical terms, benchmark names, model names, and quoted phrases verbatim.
- Return JSON only. The JSON must match the schema exactly, with no extra keys and no markdown fences.
"""


# ---------------------------------------------------------------------------
# Phase 1  –  Skim Agent
# ---------------------------------------------------------------------------


def build_skim_prompt(
    paper: PaperPacket,
    sections: Optional[Dict[str, str]] = None,
) -> str:
    payload = _section_payload(paper, sections, keys=["abstract", "conclusion"])
    schema = skim_schema()
    packet_json = json.dumps(payload, indent=2, ensure_ascii=False)
    schema_json = json.dumps(schema, indent=2, ensure_ascii=False)

    return f"""# Phase 1 — Skim Read (粗读)

You are an experienced researcher performing a first-pass skim of a paper.
Your goal is to quickly assess what the paper is about, what it concludes,
and whether it deserves a close reading.

Focus ONLY on the abstract, conclusion, and high-level metadata.
Do NOT attempt to analyze methods or algorithms — that is a later phase.

{_HARD_CONSTRAINTS}

## Field-by-field instructions
- `research_type`: Classify the paper (e.g. empirical study, theoretical framework, survey, benchmark, toolkit, position paper).
- `core_question`: One sentence stating the central research problem the paper addresses.
- `tldr_abstract`: One dense Chinese paragraph capturing the paper's topic, approach, and main finding. This is NOT a translation of the abstract — it should be a synthesis.
- `conclusion_takeaways`: Concrete takeaways from the conclusion. Each item should be a specific claim, not a vague summary.
- `initial_impression`: Brief assessment of novelty, methodological rigor, and relevance to your research interests, in Chinese.
- `reading_priority`: One of `must-read`, `worth-reading`, `skim-only`, `skip`. Follow with a one-sentence justification.
- `suggested_tags`: 3-8 short lowercase kebab-case tags classifying the paper's domain, method family, and task type (e.g. `graph-neural-network`, `retrieval-augmented-generation`). Do not repeat generic tags like `paper` or `research`.
- `key_concepts`: 5-15 key concept, method, model, or dataset names that appear in this paper. Use canonical English names (e.g. `Transformer`, `GNN`, `LoRA`). No brackets — they will be wrapped in `[[]]` automatically.

## Output schema
```json
{schema_json}
```

## Source packet
```json
{packet_json}
```
"""


# ---------------------------------------------------------------------------
# Phase 2  –  Deep Read Agent
# ---------------------------------------------------------------------------


def build_deep_read_prompt(
    paper: PaperPacket,
    skim: Optional[SkimResult] = None,
    sections: Optional[Dict[str, str]] = None,
) -> str:
    payload = _section_payload(
        paper, sections, keys=["method", "introduction", "abstract"]
    )
    if skim:
        payload["skim_result"] = skim.to_dict()
    schema = deep_read_schema()
    packet_json = json.dumps(payload, indent=2, ensure_ascii=False)
    schema_json = json.dumps(schema, indent=2, ensure_ascii=False)

    skim_context = ""
    if skim:
        skim_context = f"""
## Context from Phase 1 (Skim)
The first-pass skim identified:
- Research type: {skim.research_type}
- Core question: {skim.core_question}
- Reading priority: {skim.reading_priority}

Use this context to focus your deep reading, but do not repeat it.
"""

    return f"""# Phase 2 — Deep Read: Methods & Algorithms (精读)

You are a meticulous researcher performing a close reading of a paper's
methodology. Your task is to decompose the paper's approach into a clear,
step-by-step algorithm pipeline that a reader can follow without referring
back to the original paper.

{skim_context}
{_HARD_CONSTRAINTS}

## Special instructions for algorithm decomposition
- Break the method into discrete, ordered steps. Each step must be a concrete operation, not a vague label.
- For each step, explicitly state:
  - **Inputs**: What data or representations go in.
  - **Outputs**: What comes out.
  - **Formulas**: If the paper provides mathematical formulations (loss functions, attention mechanisms, objective functions, etc.), reproduce them in LaTeX notation. If none, write an empty string.
  - **Why it matters**: Why this step is needed in the overall pipeline.
- After the step-by-step decomposition, identify key design choices that distinguish this method from alternatives.
- List what is genuinely novel versus built on standard components.
- Record implementation details (hyperparameters, frameworks, hardware, training schedules) when present.

## Socratic open questions
- After your analysis, generate a list of `open_questions_for_reader`.
- These should be questions that a critical reader would want to answer:
  - Under-justified design choices ("Why X instead of Y?")
  - Missing ablations or comparisons
  - Scalability or generalization concerns
  - Potential failure modes
  - Connections to other approaches that are not discussed
- Frame them as genuine inquiries, not rhetorical criticisms.

## Field-by-field instructions
- `algorithm_overview`: One Chinese paragraph giving a bird's-eye view of the entire approach — how components connect, what the data flow looks like end-to-end.
- `algorithm_steps`: Ordered array of step objects. Each paper typically has 3-8 major steps. Merge trivially small operations, split genuinely complex ones.
- `key_design_choices`: Architectural or methodological decisions and their stated or implied rationale.
- `technical_novelty`: What is genuinely new compared to prior work, stated in concrete terms.
- `implementation_details`: Concrete details: model sizes, datasets used for training, hyperparameters, hardware, libraries.
- `open_questions_for_reader`: 3-6 Socratic questions for the reader to investigate further.

## Quality checklist
Before returning, verify that:
- Steps are ordered correctly with no circular dependencies
- Inputs/outputs form a coherent chain (output of step N feeds into input of step N+1 where applicable)
- Formulas are accurate transcriptions from the paper, not invented
- Open questions are specific and actionable, not generic

## Output schema
```json
{schema_json}
```

## Source packet
```json
{packet_json}
```
"""


# ---------------------------------------------------------------------------
# Phase 3  –  Discussion Agent
# ---------------------------------------------------------------------------


def build_discussion_prompt(
    paper: PaperPacket,
    skim: Optional[SkimResult] = None,
    deep_read: Optional[DeepReadResult] = None,
    sections: Optional[Dict[str, str]] = None,
) -> str:
    payload = _section_payload(
        paper, sections, keys=["experiments", "conclusion", "abstract"]
    )
    if skim:
        payload["skim_result"] = skim.to_dict()
    if deep_read:
        payload["deep_read_result"] = deep_read.to_dict()
    schema = discussion_schema()
    packet_json = json.dumps(payload, indent=2, ensure_ascii=False)
    schema_json = json.dumps(schema, indent=2, ensure_ascii=False)

    prior_context = ""
    if skim or deep_read:
        prior_context = "\n## Context from prior phases\n"
        if skim:
            prior_context += f"- Core question: {skim.core_question}\n"
            prior_context += f"- Research type: {skim.research_type}\n"
        if deep_read:
            prior_context += f"- Algorithm overview: {deep_read.algorithm_overview}\n"
            novelty = "; ".join(deep_read.technical_novelty) if deep_read.technical_novelty else "N/A"
            prior_context += f"- Technical novelty: {novelty}\n"
        prior_context += "\nUse this context but do not repeat it.\n"

    return f"""# Phase 3 — Discussion: Experiments, Limitations & Future Work (讨论)

You are a critical researcher evaluating a paper's experimental evidence,
identifying its limitations, and mapping future research directions.

{prior_context}
{_HARD_CONSTRAINTS}

## Field-by-field instructions
- `experimental_setup`: Chinese paragraph describing datasets, evaluation protocol, metrics, splits, and any important setup details. Be concrete — list actual dataset names and sizes when available.
- `baselines`: List each baseline method compared against, with a brief note on what it is (e.g. "BERT-base: pretrained transformer used as text-only baseline").
- `quantitative_results`: Array of structured results. For each key metric:
  - `metric`: Name of the metric (e.g. "F1", "Accuracy", "BLEU")
  - `value`: The paper's reported value
  - `comparison`: Relative comparison to the best baseline (e.g. "+3.2% over BERT-base")
  - `interpretation`: What this result means in plain Chinese
- `limitations_analysis`: Evidence-based limitations. Each must cite specific evidence or lack thereof. Avoid generic criticism like "needs more experiments". Focus on:
  - Threats to validity
  - Missing comparisons or ablations
  - Boundary conditions and failure modes
  - Potential confounds
  - Generalization concerns
- `future_directions`: Concrete next steps suggested or implied by the paper. Include both the authors' stated future work and your own suggestions.
- `my_critique`: A Chinese paragraph giving your balanced assessment: what is convincing, what is not, and why. Ground every claim in evidence from the packet.
- `connections_to_vault`: Links to related papers, methods, theories, or research threads that would be useful in a knowledge vault. Each item MUST use the format: `[[ConceptOrPaper]]: one-sentence description`. For example: `[[Transformer]]: the base architecture used for the encoder module`.

## Quality checklist
Before returning, verify that:
- Results are actual numbers from the paper, not fabricated
- Limitations are specific and evidence-based
- Critique is balanced — acknowledges strengths before stating weaknesses
- Future directions are actionable, not vague

## Output schema
```json
{schema_json}
```

## Source packet
```json
{packet_json}
```
"""


# ---------------------------------------------------------------------------
# Agent runners
# ---------------------------------------------------------------------------


def run_skim_agent(
    paper: PaperPacket,
    config: Any,
    *,
    sections: Optional[Dict[str, str]] = None,
) -> SkimResult:
    from .llm_client import call_llm

    prompt = build_skim_prompt(paper, sections=sections)
    schema = skim_schema()
    raw = call_llm(prompt=prompt, schema=schema, config=config, schema_name="skim_result")
    return SkimResult.from_dict(raw)


def run_deep_read_agent(
    paper: PaperPacket,
    config: Any,
    *,
    skim: Optional[SkimResult] = None,
    sections: Optional[Dict[str, str]] = None,
) -> DeepReadResult:
    from .llm_client import call_llm

    prompt = build_deep_read_prompt(paper, skim=skim, sections=sections)
    schema = deep_read_schema()
    raw = call_llm(prompt=prompt, schema=schema, config=config, schema_name="deep_read_result")
    result = DeepReadResult.from_dict(raw)
    result.validate()
    return result


def run_discussion_agent(
    paper: PaperPacket,
    config: Any,
    *,
    skim: Optional[SkimResult] = None,
    deep_read: Optional[DeepReadResult] = None,
    sections: Optional[Dict[str, str]] = None,
) -> DiscussionResult:
    from .llm_client import call_llm

    prompt = build_discussion_prompt(paper, skim=skim, deep_read=deep_read, sections=sections)
    schema = discussion_schema()
    raw = call_llm(prompt=prompt, schema=schema, config=config, schema_name="discussion_result")
    return DiscussionResult.from_dict(raw)


def run_full_reading(
    paper: PaperPacket,
    config: Any,
    *,
    sections: Optional[Dict[str, str]] = None,
    progress: Optional[Any] = None,
) -> Tuple[SkimResult, DeepReadResult, DiscussionResult]:
    """Run all three reading phases sequentially, passing context forward."""
    if progress:
        progress("Phase 1/3: Skim reading (粗读 abstract + conclusion)...")
    skim = run_skim_agent(paper, config, sections=sections)

    if progress:
        progress("Phase 2/3: Deep reading methods & algorithms (精读)...")
    deep_read = run_deep_read_agent(paper, config, skim=skim, sections=sections)

    if progress:
        progress("Phase 3/3: Discussion & critique (讨论局限性与未来方向)...")
    discussion = run_discussion_agent(
        paper, config, skim=skim, deep_read=deep_read, sections=sections
    )

    return skim, deep_read, discussion
