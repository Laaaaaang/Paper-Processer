from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional


DOI_PATTERN = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"(19|20)\d{2}")


def _run_mdls(attribute: str, pdf_path: Path) -> Optional[str]:
    result = subprocess.run(
        ["mdls", "-raw", "-name", attribute, str(pdf_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if not value or value == "(null)" or value == "null":
        return None
    return value


def _parse_mdls_array(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    if not raw.startswith("("):
        return [raw.strip('"')]
    return [item.strip().strip('",') for item in raw.strip("()").split("\n") if item.strip()]


def _infer_title_from_stem(stem: str) -> str:
    cleaned = re.sub(r"[_\-]+", " ", stem).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or stem


def _infer_year(title: str, stem: str) -> Optional[str]:
    for value in (title, stem):
        match = YEAR_PATTERN.search(value)
        if match:
            return match.group(0)
    return None


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _looks_like_garbage_title(value: Optional[str]) -> bool:
    if not value:
        return True
    candidate = value.strip()
    if len(candidate) < 6:
        return True
    alpha_count = sum(1 for char in candidate if char.isalpha())
    digit_count = sum(1 for char in candidate if char.isdigit())
    if alpha_count == 0:
        return True
    if digit_count > alpha_count:
        return True
    return False


def _extract_text_content(pdf_path: Path) -> str:
    spotlight_text = _run_mdls("kMDItemTextContent", pdf_path)
    if spotlight_text and len(spotlight_text.strip()) > 80:
        return spotlight_text

    result = subprocess.run(
        ["strings", "-n", "8", str(pdf_path)],
        check=False,
        capture_output=True,
        text=True,
        errors="ignore",
    )
    if result.returncode != 0:
        return ""
    return result.stdout[:50000]


def _extract_doi(*sources: Optional[str]) -> Optional[str]:
    for source in sources:
        if not source:
            continue
        match = DOI_PATTERN.search(source)
        if match:
            doi = match.group(1).rstrip(").,;]")
            return doi
    return None


def _extract_title_from_text(text: str) -> Optional[str]:
    lines = [_normalize_whitespace(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None

    title_lines: List[str] = []
    for line in lines[:12]:
        lower = line.lower()
        if lower.startswith(("abstract", "introduction", "keywords", "doi", "arxiv")):
            break
        if "@" in line or line.startswith("http"):
            continue
        if YEAR_PATTERN.fullmatch(line):
            continue
        if len(line) < 12:
            continue
        title_lines.append(line)
        if len(title_lines) == 2:
            break

    if not title_lines:
        return None
    candidate = _normalize_whitespace(" ".join(title_lines))
    if _looks_like_garbage_title(candidate):
        return None
    return candidate


def _extract_authors_from_text(text: str, title: Optional[str]) -> List[str]:
    lines = [_normalize_whitespace(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return []

    title_index = -1
    if title:
        for index, line in enumerate(lines[:20]):
            if title in line or line in title:
                title_index = index
                break

    search_lines = lines[title_index + 1 : title_index + 6] if title_index >= 0 else lines[:6]
    for line in search_lines:
        lower = line.lower()
        if lower.startswith(("abstract", "introduction", "keywords", "doi", "arxiv")):
            continue
        if "@" in line or "university" in lower or "department" in lower:
            continue
        if sum(1 for char in line if char.isalpha()) < 6:
            continue
        parts = [part.strip() for part in re.split(r",| and ", line) if part.strip()]
        valid = []
        for part in parts:
            words = [word for word in part.split() if word]
            if 1 < len(words) <= 4 and all(any(ch.isalpha() for ch in word) for word in words):
                valid.append(part)
        if 1 <= len(valid) <= 8:
            return valid
    return []


def _extract_abstract_from_text(text: str) -> Optional[str]:
    match = re.search(
        r"\babstract\b[:\s]*(.+?)(?:\n\s*\n|\bkeywords\b|\bintroduction\b|\n1[\s.])",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    abstract = _normalize_whitespace(match.group(1))
    if len(abstract) < 40:
        return None
    return abstract[:2500]


def _strip_jats_tags(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return _normalize_whitespace(without_tags)


def _extract_year_from_crossref(message: Dict[str, object]) -> Optional[str]:
    for key in ("published-print", "published-online", "issued", "created"):
        data = message.get(key)
        if isinstance(data, dict):
            parts = data.get("date-parts")
            if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
                return str(parts[0][0])
    return None


def _fetch_crossref_metadata(doi: str) -> Dict[str, Optional[object]]:
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "research-flow/0.1 (metadata autofill)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return {}

    message = payload.get("message")
    if not isinstance(message, dict):
        return {}

    authors: List[str] = []
    for author in message.get("author", []) if isinstance(message.get("author"), list) else []:
        if not isinstance(author, dict):
            continue
        given = _normalize_whitespace(str(author.get("given") or ""))
        family = _normalize_whitespace(str(author.get("family") or ""))
        literal = _normalize_whitespace(str(author.get("name") or ""))
        if given or family:
            authors.append(_normalize_whitespace(f"{given} {family}"))
        elif literal:
            authors.append(literal)

    titles = message.get("title")
    title = titles[0] if isinstance(titles, list) and titles else None
    journals = message.get("container-title")
    journal = journals[0] if isinstance(journals, list) and journals else None
    abstract = message.get("abstract")
    cleaned_abstract = _strip_jats_tags(abstract) if isinstance(abstract, str) else None

    return {
        "title": _normalize_whitespace(str(title)) if title else None,
        "authors": authors or None,
        "year": _extract_year_from_crossref(message),
        "journal": _normalize_whitespace(str(journal)) if journal else None,
        "doi": doi,
        "url": _normalize_whitespace(str(message.get("URL") or "")) or None,
        "abstract": cleaned_abstract,
    }


def extract_pdf_metadata(pdf_path: Path) -> Dict[str, object]:
    raw_title = _run_mdls("kMDItemTitle", pdf_path)
    fallback_title = _infer_title_from_stem(pdf_path.stem)
    text_content = _extract_text_content(pdf_path)
    text_title = _extract_title_from_text(text_content)
    title = raw_title if not _looks_like_garbage_title(raw_title) else None
    title = title or text_title or fallback_title

    authors = _parse_mdls_array(_run_mdls("kMDItemAuthors", pdf_path))
    if not authors:
        authors = _extract_authors_from_text(text_content, text_title or title)

    where_from = _run_mdls("kMDItemWhereFroms", pdf_path)
    doi = _extract_doi(raw_title, fallback_title, where_from, text_content)
    crossref = _fetch_crossref_metadata(doi) if doi else {}

    if crossref.get("title") and (_looks_like_garbage_title(title) or title == fallback_title):
        title = str(crossref["title"])
    if crossref.get("authors") and not authors:
        authors = [str(author) for author in crossref["authors"] if author]

    year = (
        str(crossref.get("year"))
        if crossref.get("year")
        else _infer_year(title, pdf_path.stem)
    )

    url = None
    if where_from and "http" in where_from:
        match = re.search(r"https?://[^\", )]+", where_from)
        if match:
            url = match.group(0)
    url = url or (str(crossref.get("url")) if crossref.get("url") else None)

    abstract = _extract_abstract_from_text(text_content) or (
        str(crossref.get("abstract")) if crossref.get("abstract") else None
    )

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "journal": str(crossref.get("journal")) if crossref.get("journal") else None,
        "doi": doi,
        "url": url,
        "abstract": abstract,
        "annotation_text": None,
    }
