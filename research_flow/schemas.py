from __future__ import annotations

from typing import Any, Dict


def analysis_schema() -> Dict[str, Any]:
    """Legacy single-pass analysis schema (backward compatible)."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "chinese_summary": {"type": "string"},
            "english_abstract_snapshot": {"type": "string"},
            "core_question": {"type": "string"},
            "methods": {"type": "array", "items": {"type": "string"}},
            "key_findings": {"type": "array", "items": {"type": "string"}},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "limitations": {"type": "array", "items": {"type": "string"}},
            "useful_quotes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "quote": {"type": "string"},
                        "page_label": {"type": "string"},
                        "why_it_matters": {"type": "string"},
                    },
                    "required": ["quote", "page_label", "why_it_matters"],
                },
            },
            "my_connections": {"type": "array", "items": {"type": "string"}},
            "next_actions": {"type": "array", "items": {"type": "string"}},
            "suggested_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-8 short lowercase kebab-case tags classifying the paper's domain, method family, and task type. Examples: graph-neural-network, retrieval-augmented-generation, claim-verification.",
            },
            "key_concepts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "5-15 key concept, method, model, or dataset names that appear in this paper and would be useful as wiki-link nodes in a knowledge graph. Use canonical names (e.g. Transformer, GNN, RAG, LoRA). No brackets.",
            },
        },
        "required": [
            "chinese_summary",
            "english_abstract_snapshot",
            "core_question",
            "methods",
            "key_findings",
            "strengths",
            "limitations",
            "useful_quotes",
            "my_connections",
            "next_actions",
            "suggested_tags",
            "key_concepts",
        ],
    }


def skim_schema() -> Dict[str, Any]:
    """Phase 1: Quick read of abstract + conclusion."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "research_type": {
                "type": "string",
                "description": "Category such as empirical, theoretical, survey, benchmark, toolkit, etc.",
            },
            "core_question": {
                "type": "string",
                "description": "One sentence stating the central research problem.",
            },
            "tldr_abstract": {
                "type": "string",
                "description": "Dense Chinese paragraph summarizing what the paper is about, what it does, and what it finds.",
            },
            "conclusion_takeaways": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key takeaways extracted from the conclusion section.",
            },
            "initial_impression": {
                "type": "string",
                "description": "Brief assessment of novelty, relevance, and potential value before deep reading.",
            },
            "reading_priority": {
                "type": "string",
                "description": "One of: must-read, worth-reading, skim-only, skip. With one-sentence justification.",
            },
            "suggested_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-8 short lowercase kebab-case tags classifying the paper's domain, method family, and task type. Examples: graph-neural-network, retrieval-augmented-generation, claim-verification.",
            },
            "key_concepts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "5-15 key concept, method, model, or dataset names that appear in this paper and would be useful as wiki-link nodes in a knowledge graph. Use canonical names (e.g. Transformer, GNN, RAG, LoRA). No brackets.",
            },
        },
        "required": [
            "research_type",
            "core_question",
            "tldr_abstract",
            "conclusion_takeaways",
            "initial_impression",
            "reading_priority",
            "suggested_tags",
            "key_concepts",
        ],
    }


def deep_read_schema() -> Dict[str, Any]:
    """Phase 2: Close reading of methods and algorithms."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "algorithm_overview": {
                "type": "string",
                "description": "One paragraph in Chinese explaining the overall approach and how components fit together.",
            },
            "algorithm_steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "step_name": {"type": "string"},
                        "description": {
                            "type": "string",
                            "description": "What this step does, in concrete terms.",
                        },
                        "inputs": {"type": "string"},
                        "outputs": {"type": "string"},
                        "formulas": {
                            "type": "string",
                            "description": "Key equations or formal definitions in LaTeX if present, otherwise empty string.",
                        },
                        "why_it_matters": {
                            "type": "string",
                            "description": "Why this step is necessary for the overall method.",
                        },
                    },
                    "required": [
                        "step_name",
                        "description",
                        "inputs",
                        "outputs",
                        "formulas",
                        "why_it_matters",
                    ],
                },
                "description": "Ordered list of algorithm or method steps, decomposed into an input-process-output chain.",
            },
            "key_design_choices": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Important architectural or design decisions and their rationale.",
            },
            "technical_novelty": {
                "type": "array",
                "items": {"type": "string"},
                "description": "What is genuinely new compared to prior work.",
            },
            "implementation_details": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Concrete implementation details: hyperparameters, frameworks, training setup, etc.",
            },
            "open_questions_for_reader": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Socratic-style questions the reader should investigate further. Things that are unclear, under-justified, or worth verifying.",
            },
        },
        "required": [
            "algorithm_overview",
            "algorithm_steps",
            "key_design_choices",
            "technical_novelty",
            "implementation_details",
            "open_questions_for_reader",
        ],
    }


def discussion_schema() -> Dict[str, Any]:
    """Phase 3: Experimental evaluation, limitations, and future directions."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "experimental_setup": {
                "type": "string",
                "description": "Datasets, evaluation protocol, metrics used, and any important setup details.",
            },
            "baselines": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of baseline methods or systems compared against, with brief description of each.",
            },
            "quantitative_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "metric": {"type": "string"},
                        "value": {"type": "string"},
                        "comparison": {
                            "type": "string",
                            "description": "How this compares to the best baseline (e.g. '+3.2% over XYZ').",
                        },
                        "interpretation": {
                            "type": "string",
                            "description": "What this result means in context.",
                        },
                    },
                    "required": ["metric", "value", "comparison", "interpretation"],
                },
            },
            "limitations_analysis": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Evidence-based limitations, failure modes, and boundary conditions.",
            },
            "future_directions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Concrete future work directions mentioned or implied by the paper.",
            },
            "my_critique": {
                "type": "string",
                "description": "Reader-oriented critical assessment: what is convincing, what is not, and why.",
            },
            "connections_to_vault": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Links to related papers, methods, theories, or projects in the knowledge vault. Each item MUST use the format: [[ConceptOrPaper]]: one-sentence description of the connection.",
            },
        },
        "required": [
            "experimental_setup",
            "baselines",
            "quantitative_results",
            "limitations_analysis",
            "future_directions",
            "my_critique",
            "connections_to_vault",
        ],
    }
