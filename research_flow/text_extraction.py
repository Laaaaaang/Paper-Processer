"""Extract full text from PDF and segment into paper sections.

Supports pymupdf (preferred) with fallback to pdftotext (poppler).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Section heading patterns (order matters — first match wins)
_HEADING_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("abstract", re.compile(r"^\s*abstract\b", re.IGNORECASE)),
    ("introduction", re.compile(r"^\s*(?:\d+[\.\s]*)?introduction\b", re.IGNORECASE)),
    ("related_work", re.compile(r"^\s*(?:\d+[\.\s]*)?related\s+work\b", re.IGNORECASE)),
    ("method", re.compile(
        r"^\s*(?:\d+[\.\s]*)?"
        r"(?:method(?:ology|s)?|approach|proposed\s+(?:method|approach|framework|model)"
        r"|our\s+(?:method|approach|framework|model)|framework|model\s+architecture"
        r"|algorithm|system\s+(?:design|overview|architecture))\b",
        re.IGNORECASE,
    )),
    ("experiments", re.compile(
        r"^\s*(?:\d+[\.\s]*)?"
        r"(?:experiment(?:s|al)?(?:\s+(?:results|setup|evaluation))?"
        r"|evaluation|results(?:\s+and\s+(?:analysis|discussion))?"
        r"|empirical\s+(?:study|evaluation|analysis))\b",
        re.IGNORECASE,
    )),
    ("discussion", re.compile(
        r"^\s*(?:\d+[\.\s]*)?discussion\b", re.IGNORECASE
    )),
    ("conclusion", re.compile(
        r"^\s*(?:\d+[\.\s]*)?"
        r"(?:conclusion(?:s)?(?:\s+and\s+future\s+work)?"
        r"|summary(?:\s+and\s+(?:future\s+work|conclusion))?"
        r"|concluding\s+remarks)\b",
        re.IGNORECASE,
    )),
    ("references", re.compile(r"^\s*(?:\d+[\.\s]*)?references\b", re.IGNORECASE)),
]


def _extract_with_pymupdf(pdf_path: Path) -> Optional[str]:
    """Try extracting text using pymupdf (fitz)."""
    try:
        import fitz  # type: ignore[import-untyped]
    except ImportError:
        return None

    try:
        doc = fitz.open(str(pdf_path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n\n".join(pages)
    except Exception:
        return None


def _extract_with_pdftotext(pdf_path: Path) -> Optional[str]:
    """Try extracting text using pdftotext (poppler)."""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=False,
            capture_output=True,
            text=True,
            errors="ignore",
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return text if text else None


def extract_full_text(pdf_path: Path) -> str:
    """Extract full text from PDF, trying pymupdf first then pdftotext."""
    text = _extract_with_pymupdf(pdf_path)
    if text and len(text.strip()) > 100:
        return text

    text = _extract_with_pdftotext(pdf_path)
    if text and len(text.strip()) > 100:
        return text

    raise RuntimeError(
        f"Could not extract text from {pdf_path}. "
        "Install pymupdf (`pip install pymupdf`) or pdftotext (poppler)."
    )


def _classify_line(line: str) -> Optional[str]:
    """Return section key if line looks like a section heading, else None."""
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return None
    for key, pattern in _HEADING_PATTERNS:
        if pattern.match(stripped):
            return key
    return None


def segment_sections(full_text: str) -> Dict[str, str]:
    """Split extracted text into named sections.

    Returns a dict with keys like 'abstract', 'method', 'experiments', etc.
    Also always includes 'full_text'.
    """
    lines = full_text.splitlines()
    segments: List[Tuple[str, int]] = []

    for idx, line in enumerate(lines):
        section = _classify_line(line)
        if section:
            segments.append((section, idx))

    if not segments:
        return {"full_text": full_text}

    result: Dict[str, str] = {"full_text": full_text}
    for i, (key, start) in enumerate(segments):
        end = segments[i + 1][1] if i + 1 < len(segments) else len(lines)
        # Skip the heading line itself
        body = "\n".join(lines[start + 1 : end]).strip()
        if body:
            # If same section key appears multiple times, append
            if key in result and key != "full_text":
                result[key] += "\n\n" + body
            else:
                result[key] = body

    return result


def extract_and_segment(pdf_path: Path) -> Dict[str, str]:
    """Full pipeline: extract text from PDF and segment into sections."""
    full_text = extract_full_text(pdf_path)
    return segment_sections(full_text)


def save_extracted_sections(sections: Dict[str, str], output_path: Path) -> None:
    """Save extracted sections to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sections, f, indent=2, ensure_ascii=False)


def load_extracted_sections(path: Path) -> Dict[str, str]:
    """Load previously extracted sections from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
