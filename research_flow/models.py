from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def _string_list(value: Any, field_name: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a string or list of strings")
    result: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must contain only strings")
        cleaned = item.strip()
        if cleaned:
            result.append(cleaned)
    return result


def _optional_string(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    cleaned = value.strip()
    return cleaned or None


def _required_string(value: Any, field_name: str) -> str:
    cleaned = _optional_string(value, field_name)
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    return cleaned


def _int_or_string(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    raise ValueError(f"{field_name} must be an integer or string")


@dataclass
class Annotation:
    text: str
    comment: Optional[str] = None
    page_label: Optional[str] = None
    color: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Annotation":
        if not isinstance(data, dict):
            raise ValueError("annotations entries must be objects")
        return cls(
            text=_required_string(data.get("text"), "annotations[].text"),
            comment=_optional_string(data.get("comment"), "annotations[].comment"),
            page_label=_optional_string(
                _int_or_string(data.get("page_label"), "annotations[].page_label"),
                "annotations[].page_label",
            ),
            color=_optional_string(data.get("color"), "annotations[].color"),
        )

    def to_display_block(self) -> str:
        segments = [self.text]
        if self.comment:
            segments.append(f"Comment: {self.comment}")
        if self.page_label:
            segments.append(f"Page: {self.page_label}")
        if self.color:
            segments.append(f"Color: {self.color}")
        return " | ".join(segments)


@dataclass
class PaperPacket:
    citekey: str
    zotero_item_key: str
    title: str
    authors: List[str]
    year: Optional[str] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    annotation_text: Optional[str] = None
    pdf_path: Optional[str] = None
    extracted_text_path: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    status: str = "draft"
    annotations: List[Annotation] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PaperPacket":
        if not isinstance(data, dict):
            raise ValueError("paper packet must be a JSON object")

        annotations_data = data.get("annotations") or []
        if annotations_data and not isinstance(annotations_data, list):
            raise ValueError("annotations must be a list")

        return cls(
            citekey=_required_string(data.get("citekey"), "citekey"),
            zotero_item_key=_required_string(data.get("zotero_item_key"), "zotero_item_key"),
            title=_required_string(data.get("title"), "title"),
            authors=_string_list(data.get("authors"), "authors"),
            year=_int_or_string(data.get("year"), "year"),
            journal=_optional_string(data.get("journal"), "journal"),
            doi=_optional_string(data.get("doi"), "doi"),
            url=_optional_string(data.get("url"), "url"),
            abstract=_optional_string(data.get("abstract"), "abstract"),
            annotation_text=_optional_string(data.get("annotation_text"), "annotation_text"),
            pdf_path=_optional_string(data.get("pdf_path"), "pdf_path"),
            extracted_text_path=_optional_string(
                data.get("extracted_text_path"), "extracted_text_path"
            ),
            tags=_string_list(data.get("tags"), "tags"),
            status=_required_string(data.get("status") or "draft", "status"),
            annotations=[Annotation.from_dict(item) for item in annotations_data],
        )

    def validate(self) -> None:
        if not self.authors:
            raise ValueError("authors must include at least one author")

    def short_title_slug(self, max_length: int = 48) -> str:
        cleaned = []
        previous_dash = False
        for char in self.title.lower():
            if char.isalnum():
                cleaned.append(char)
                previous_dash = False
            elif not previous_dash:
                cleaned.append("-")
                previous_dash = True
        slug = "".join(cleaned).strip("-")
        if len(slug) <= max_length:
            return slug
        truncated = slug[:max_length].rstrip("-")
        return truncated or "paper"

    def note_relative_path(self) -> Path:
        filename = f"{self.citekey} - {self.short_title_slug()}.md"
        return Path("Literature") / filename

    def source_summary(self) -> Dict[str, Any]:
        return {
            "citekey": self.citekey,
            "zotero_item_key": self.zotero_item_key,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "journal": self.journal,
            "doi": self.doi,
            "url": self.url,
            "abstract": self.abstract,
            "annotation_text": self.annotation_text,
            "pdf_path": self.pdf_path,
            "extracted_text_path": self.extracted_text_path,
            "tags": self.tags,
            "status": self.status,
            "annotations": [
                {
                    "text": annotation.text,
                    "comment": annotation.comment,
                    "page_label": annotation.page_label,
                    "color": annotation.color,
                }
                for annotation in self.annotations
            ],
        }


@dataclass
class UsefulQuote:
    quote: str
    page_label: Optional[str]
    why_it_matters: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UsefulQuote":
        if not isinstance(data, dict):
            raise ValueError("useful_quotes entries must be objects")
        return cls(
            quote=_required_string(data.get("quote"), "useful_quotes[].quote"),
            page_label=_optional_string(
                _int_or_string(data.get("page_label"), "useful_quotes[].page_label"),
                "useful_quotes[].page_label",
            ),
            why_it_matters=_required_string(
                data.get("why_it_matters"), "useful_quotes[].why_it_matters"
            ),
        )


@dataclass
class AnalysisPacket:
    chinese_summary: str
    english_abstract_snapshot: str
    core_question: str
    methods: List[str]
    key_findings: List[str]
    strengths: List[str]
    limitations: List[str]
    useful_quotes: List[UsefulQuote]
    my_connections: List[str]
    next_actions: List[str]
    suggested_tags: List[str] = field(default_factory=list)
    key_concepts: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisPacket":
        if not isinstance(data, dict):
            raise ValueError("analysis packet must be a JSON object")
        packet = cls(
            chinese_summary=_required_string(data.get("chinese_summary"), "chinese_summary"),
            english_abstract_snapshot=_required_string(
                data.get("english_abstract_snapshot"), "english_abstract_snapshot"
            ),
            core_question=_required_string(data.get("core_question"), "core_question"),
            methods=_string_list(data.get("methods"), "methods"),
            key_findings=_string_list(data.get("key_findings"), "key_findings"),
            strengths=_string_list(data.get("strengths"), "strengths"),
            limitations=_string_list(data.get("limitations"), "limitations"),
            useful_quotes=[
                UsefulQuote.from_dict(item) for item in (data.get("useful_quotes") or [])
            ],
            my_connections=_string_list(data.get("my_connections"), "my_connections"),
            next_actions=_string_list(data.get("next_actions"), "next_actions"),
            suggested_tags=_string_list(data.get("suggested_tags") or [], "suggested_tags"),
            key_concepts=_string_list(data.get("key_concepts") or [], "key_concepts"),
        )
        packet.validate()
        return packet

    def validate(self) -> None:
        list_fields = {
            "methods": self.methods,
            "key_findings": self.key_findings,
            "strengths": self.strengths,
            "limitations": self.limitations,
            "my_connections": self.my_connections,
            "next_actions": self.next_actions,
        }
        for field_name, values in list_fields.items():
            if not values:
                raise ValueError(f"{field_name} must contain at least one item")


# ---------------------------------------------------------------------------
# Phase-based reading result models
# ---------------------------------------------------------------------------


@dataclass
class SkimResult:
    """Phase 1: Quick read of abstract + conclusion."""

    research_type: str
    core_question: str
    tldr_abstract: str
    conclusion_takeaways: List[str]
    initial_impression: str
    reading_priority: str
    suggested_tags: List[str] = field(default_factory=list)
    key_concepts: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkimResult":
        if not isinstance(data, dict):
            raise ValueError("skim result must be a JSON object")
        return cls(
            research_type=_required_string(data.get("research_type"), "research_type"),
            core_question=_required_string(data.get("core_question"), "core_question"),
            tldr_abstract=_required_string(data.get("tldr_abstract"), "tldr_abstract"),
            conclusion_takeaways=_string_list(
                data.get("conclusion_takeaways"), "conclusion_takeaways"
            ),
            initial_impression=_required_string(
                data.get("initial_impression"), "initial_impression"
            ),
            reading_priority=_required_string(data.get("reading_priority"), "reading_priority"),
            suggested_tags=_string_list(data.get("suggested_tags") or [], "suggested_tags"),
            key_concepts=_string_list(data.get("key_concepts") or [], "key_concepts"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "research_type": self.research_type,
            "core_question": self.core_question,
            "tldr_abstract": self.tldr_abstract,
            "conclusion_takeaways": self.conclusion_takeaways,
            "initial_impression": self.initial_impression,
            "reading_priority": self.reading_priority,
            "suggested_tags": self.suggested_tags,
            "key_concepts": self.key_concepts,
        }


@dataclass
class AlgorithmStep:
    """One step in an algorithm or method pipeline."""

    step_name: str
    description: str
    inputs: str
    outputs: str
    formulas: Optional[str] = None
    why_it_matters: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlgorithmStep":
        if not isinstance(data, dict):
            raise ValueError("algorithm_steps entries must be objects")
        return cls(
            step_name=_required_string(data.get("step_name"), "step_name"),
            description=_required_string(data.get("description"), "description"),
            inputs=_required_string(data.get("inputs"), "inputs"),
            outputs=_required_string(data.get("outputs"), "outputs"),
            formulas=_optional_string(data.get("formulas"), "formulas"),
            why_it_matters=_optional_string(data.get("why_it_matters"), "why_it_matters"),
        )


@dataclass
class DeepReadResult:
    """Phase 2: Close reading of methods and algorithms."""

    algorithm_overview: str
    algorithm_steps: List[AlgorithmStep]
    key_design_choices: List[str]
    technical_novelty: List[str]
    implementation_details: List[str]
    open_questions_for_reader: List[str]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeepReadResult":
        if not isinstance(data, dict):
            raise ValueError("deep read result must be a JSON object")
        return cls(
            algorithm_overview=_required_string(
                data.get("algorithm_overview"), "algorithm_overview"
            ),
            algorithm_steps=[
                AlgorithmStep.from_dict(item)
                for item in (data.get("algorithm_steps") or [])
            ],
            key_design_choices=_string_list(
                data.get("key_design_choices"), "key_design_choices"
            ),
            technical_novelty=_string_list(data.get("technical_novelty"), "technical_novelty"),
            implementation_details=_string_list(
                data.get("implementation_details"), "implementation_details"
            ),
            open_questions_for_reader=_string_list(
                data.get("open_questions_for_reader"), "open_questions_for_reader"
            ),
        )

    def validate(self) -> None:
        if not self.algorithm_steps:
            raise ValueError("algorithm_steps must contain at least one step")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "algorithm_overview": self.algorithm_overview,
            "algorithm_steps": [
                {
                    "step_name": step.step_name,
                    "description": step.description,
                    "inputs": step.inputs,
                    "outputs": step.outputs,
                    "formulas": step.formulas or "",
                    "why_it_matters": step.why_it_matters or "",
                }
                for step in self.algorithm_steps
            ],
            "key_design_choices": self.key_design_choices,
            "technical_novelty": self.technical_novelty,
            "implementation_details": self.implementation_details,
            "open_questions_for_reader": self.open_questions_for_reader,
        }


@dataclass
class QuantitativeResult:
    """A single metric result from experiments."""

    metric: str
    value: str
    comparison: str
    interpretation: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuantitativeResult":
        if not isinstance(data, dict):
            raise ValueError("quantitative_results entries must be objects")
        return cls(
            metric=_required_string(data.get("metric"), "metric"),
            value=_required_string(data.get("value"), "value"),
            comparison=_required_string(data.get("comparison"), "comparison"),
            interpretation=_required_string(data.get("interpretation"), "interpretation"),
        )


@dataclass
class DiscussionResult:
    """Phase 3: Experimental evaluation, limitations, and future directions."""

    experimental_setup: str
    baselines: List[str]
    quantitative_results: List[QuantitativeResult]
    limitations_analysis: List[str]
    future_directions: List[str]
    my_critique: str
    connections_to_vault: List[str]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiscussionResult":
        if not isinstance(data, dict):
            raise ValueError("discussion result must be a JSON object")
        return cls(
            experimental_setup=_required_string(
                data.get("experimental_setup"), "experimental_setup"
            ),
            baselines=_string_list(data.get("baselines"), "baselines"),
            quantitative_results=[
                QuantitativeResult.from_dict(item)
                for item in (data.get("quantitative_results") or [])
            ],
            limitations_analysis=_string_list(
                data.get("limitations_analysis"), "limitations_analysis"
            ),
            future_directions=_string_list(data.get("future_directions"), "future_directions"),
            my_critique=_required_string(data.get("my_critique"), "my_critique"),
            connections_to_vault=_string_list(
                data.get("connections_to_vault"), "connections_to_vault"
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experimental_setup": self.experimental_setup,
            "baselines": self.baselines,
            "quantitative_results": [
                {
                    "metric": r.metric,
                    "value": r.value,
                    "comparison": r.comparison,
                    "interpretation": r.interpretation,
                }
                for r in self.quantitative_results
            ],
            "limitations_analysis": self.limitations_analysis,
            "future_directions": self.future_directions,
            "my_critique": self.my_critique,
            "connections_to_vault": self.connections_to_vault,
        }

