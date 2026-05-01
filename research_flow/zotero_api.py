from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import AppConfig


ZOTERO_API_BASE = "https://api.zotero.org"
ZOTERO_CONNECTOR_API_VERSION = "3"


class ZoteroAPIError(RuntimeError):
    pass


class ZoteroDesktopError(RuntimeError):
    pass


def _request_json(
    request: urllib.request.Request,
    expected_statuses: List[int],
) -> Any:
    try:
        with urllib.request.urlopen(request, context=ssl.create_default_context()) as response:
            body = response.read().decode("utf-8")
            if response.status not in expected_statuses:
                raise ZoteroAPIError(
                    f"Unexpected Zotero response status: {response.status} {body}"
                )
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ZoteroAPIError(f"Zotero API error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise ZoteroAPIError(f"Zotero API request failed: {exc}") from exc


def _json_request(
    request: urllib.request.Request,
    expected_statuses: List[int],
) -> Dict[str, Any]:
    payload = _request_json(request, expected_statuses)
    if not isinstance(payload, dict):
        raise ZoteroAPIError(f"Unexpected Zotero API payload shape: {type(payload).__name__}")
    return payload


def _request_json_with_headers(
    request: urllib.request.Request,
    expected_statuses: List[int],
) -> tuple[Any, Dict[str, str]]:
    try:
        with urllib.request.urlopen(request, context=ssl.create_default_context()) as response:
            body = response.read().decode("utf-8")
            if response.status not in expected_statuses:
                raise ZoteroAPIError(
                    f"Unexpected Zotero response status: {response.status} {body}"
                )
            payload = json.loads(body) if body else {}
            headers = {key.lower(): value for key, value in response.headers.items()}
            return payload, headers
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ZoteroAPIError(f"Zotero API error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise ZoteroAPIError(f"Zotero API request failed: {exc}") from exc


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split()).strip()


def _normalize_text(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else " " for ch in value)


def _surname(name: str) -> str:
    parts = [part for part in name.split() if part]
    return parts[-1].lower() if parts else ""


def _extract_year(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    for token in value.split():
        if len(token) == 4 and token.isdigit() and token.startswith(("19", "20")):
            return token
    import re

    match = re.search(r"(19|20)\d{2}", value)
    return match.group(0) if match else None


def _normalize_filename(value: str) -> str:
    return _normalize_text(Path(value).stem)


def _item_to_metadata(item: Dict[str, Any]) -> Dict[str, Any]:
    data = item.get("data", {})
    if not isinstance(data, dict):
        data = {}
    creators = data.get("creators") if isinstance(data.get("creators"), list) else []
    authors: List[str] = []
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        if creator.get("creatorType") != "author":
            continue
        first = _normalize_whitespace(str(creator.get("firstName") or ""))
        last = _normalize_whitespace(str(creator.get("lastName") or ""))
        literal = _normalize_whitespace(str(creator.get("name") or ""))
        if first or last:
            authors.append(_normalize_whitespace(f"{first} {last}"))
        elif literal:
            authors.append(literal)

    journal = None
    for field in ("publicationTitle", "proceedingsTitle", "bookTitle", "seriesTitle"):
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            journal = _normalize_whitespace(value)
            break

    return {
        "zotero_item_key": item.get("key") or data.get("key"),
        "title": _normalize_whitespace(str(data.get("title") or "")) or None,
        "authors": authors,
        "year": _extract_year(str(data.get("date") or "")),
        "journal": journal,
        "doi": _normalize_whitespace(str(data.get("DOI") or "")) or None,
        "url": _normalize_whitespace(str(data.get("url") or "")) or None,
        "abstract": _normalize_whitespace(str(data.get("abstractNote") or "")) or None,
        "item_type": _normalize_whitespace(str(data.get("itemType") or "")) or None,
        "filename": _normalize_whitespace(str(data.get("filename") or "")) or None,
        "date_modified": _normalize_whitespace(str(data.get("dateModified") or "")) or None,
    }


def _score_metadata_candidate(
    candidate: Dict[str, Any],
    *,
    title: Optional[str],
    authors: Optional[List[str]],
    year: Optional[str],
    doi: Optional[str],
) -> int:
    score = 0
    candidate_title = str(candidate.get("title") or "")
    candidate_doi = str(candidate.get("doi") or "").lower()
    normalized_title = _normalize_text(title or "")
    normalized_candidate_title = _normalize_text(candidate_title)
    if doi and candidate_doi and candidate_doi == doi.lower():
        score += 120
    if normalized_title and normalized_candidate_title:
        if normalized_title == normalized_candidate_title:
            score += 80
        elif normalized_title in normalized_candidate_title or normalized_candidate_title in normalized_title:
            score += 55
        else:
            wanted_tokens = set(normalized_title.split())
            candidate_tokens = set(normalized_candidate_title.split())
            overlap = len(wanted_tokens & candidate_tokens)
            if overlap:
                score += min(35, overlap * 6)
    candidate_year = str(candidate.get("year") or "")
    if year and candidate_year and year == candidate_year:
        score += 20
    candidate_authors = [str(author) for author in candidate.get("authors") or []]
    if authors and candidate_authors:
        wanted_surnames = {_surname(author) for author in authors if _surname(author)}
        candidate_surnames = {_surname(author) for author in candidate_authors if _surname(author)}
        overlap = len(wanted_surnames & candidate_surnames)
        if overlap:
            score += min(30, overlap * 12)
    return score


def _score_attachment_candidate(
    children: List[Dict[str, Any]],
    *,
    pdf_path: Path,
) -> tuple[int, Optional[str]]:
    wanted_name = pdf_path.name.lower()
    wanted_stem = _normalize_filename(pdf_path.name)
    best_score = 0
    best_key: Optional[str] = None

    for child in children:
        metadata = _item_to_metadata(child)
        if metadata.get("item_type") != "attachment":
            continue
        child_key = str(metadata.get("zotero_item_key") or "") or None
        variants = [
            str(metadata.get("filename") or ""),
            str(metadata.get("title") or ""),
        ]
        for variant in variants:
            cleaned = variant.strip()
            if not cleaned:
                continue
            normalized_stem = _normalize_filename(cleaned)
            lowered = cleaned.lower()
            score = 0
            if lowered == wanted_name:
                score = 160
            elif normalized_stem and normalized_stem == wanted_stem:
                score = 145
            elif normalized_stem and (normalized_stem in wanted_stem or wanted_stem in normalized_stem):
                score = 115
            if score > best_score:
                best_score = score
                best_key = child_key
    return best_score, best_key


_ZOTERO_STORAGE_DIRS = [
    Path.home() / "Zotero" / "storage",
    Path.home() / "Documents" / "Zotero" / "storage",
]


def _read_local_storage_pdf(att_key: str, fallback_filename: str = "") -> Optional[tuple]:
    """Try to read a PDF from Zotero's local storage directory.

    Zotero stores attachments as ``<storage_dir>/<attachment_key>/<filename>``.
    Returns ``(filename, pdf_bytes)`` or ``None``.
    """
    for storage_dir in _ZOTERO_STORAGE_DIRS:
        item_dir = storage_dir / att_key
        if not item_dir.is_dir():
            continue
        for candidate in item_dir.iterdir():
            if candidate.suffix.lower() == ".pdf" and candidate.is_file():
                try:
                    pdf_bytes = candidate.read_bytes()
                    if pdf_bytes and len(pdf_bytes) > 100:
                        return (candidate.name, pdf_bytes)
                except OSError:
                    continue
    return None


class ZoteroClient:
    def __init__(self, config: AppConfig):
        config.require_zotero()
        self.config = config
        self.library_prefix = f"/{config.zotero_library_type}/{config.zotero_user_id}"

    def _api_url(self, path: str) -> str:
        return ZOTERO_API_BASE + self.library_prefix + path

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Zotero-API-Key": self.config.zotero_api_key,
            "Content-Type": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def _post_items(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        request = urllib.request.Request(
            self._api_url("/items"),
            data=json.dumps(items).encode("utf-8"),
            headers=self._headers({"Zotero-Write-Token": secrets.token_hex(16)}),
            method="POST",
        )
        payload = _json_request(request, expected_statuses=[200])
        if "successful" not in payload:
            raise ZoteroAPIError(f"Unexpected Zotero item creation payload: {payload}")
        return payload

    def _get_array(self, path: str, params: Dict[str, str]) -> List[Dict[str, Any]]:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            self._api_url(f"{path}?{query}"),
            headers={"Zotero-API-Key": self.config.zotero_api_key},
            method="GET",
        )
        payload = _request_json(request, expected_statuses=[200])
        if not isinstance(payload, list):
            raise ZoteroAPIError(f"Unexpected Zotero array payload: {type(payload).__name__}")
        return [item for item in payload if isinstance(item, dict)]

    def quick_search(self, query: str, *, qmode: str = "titleCreatorYear", limit: int = 10) -> List[Dict[str, Any]]:
        return self._get_array(
            "/items",
            {
                "format": "json",
                "q": query,
                "qmode": qmode,
                "limit": str(limit),
            },
        )

    def search_top_items(
        self,
        query: str,
        *,
        qmode: str = "titleCreatorYear",
        limit: int = 10,
        since: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        params = {
            "format": "json",
            "q": query,
            "qmode": qmode,
            "limit": str(limit),
            "sort": "dateModified",
            "direction": "desc",
        }
        if since is not None:
            params["since"] = str(since)
        return self._get_array("/items/top", params)

    def fetch_children(self, item_key: str) -> List[Dict[str, Any]]:
        return self._get_array(
            f"/items/{item_key}/children",
            {
                "format": "json",
                "sort": "dateModified",
                "direction": "desc",
            },
        )

    def get_item_metadata(self, item_key: str) -> Optional[Dict[str, Any]]:
        """Fetch normalised metadata for a single library item."""
        request = urllib.request.Request(
            self._api_url(f"/items/{item_key}"),
            headers={"Zotero-API-Key": self.config.zotero_api_key},
            method="GET",
        )
        item = _json_request(request, expected_statuses=[200])
        return _item_to_metadata(item)

    def get_item_pdf(self, item_key: str) -> Optional[tuple]:
        """Download the first PDF attachment of *item_key*.

        Returns ``(filename, pdf_bytes)`` or ``None``.
        Tries the Zotero Web API first, then falls back to the local
        Zotero storage directory (``~/Zotero/storage/{att_key}/``).
        """
        children = self.fetch_children(item_key)
        for child in children:
            data = child.get("data", {})
            if not isinstance(data, dict):
                continue
            content_type = str(data.get("contentType") or "")
            if "pdf" not in content_type.lower():
                continue
            att_key = child.get("key") or data.get("key")
            if not att_key:
                continue
            filename = str(data.get("filename") or "").strip() or f"{item_key}.pdf"

            # --- Try web API download ---
            request = urllib.request.Request(
                self._api_url(f"/items/{att_key}/file"),
                headers={"Zotero-API-Key": self.config.zotero_api_key},
                method="GET",
            )
            try:
                with urllib.request.urlopen(request, context=ssl.create_default_context()) as resp:
                    pdf_bytes = resp.read()
                    if pdf_bytes and len(pdf_bytes) > 100:
                        return (filename, pdf_bytes)
            except (urllib.error.HTTPError, urllib.error.URLError):
                pass

            # --- Fallback: read from Zotero local storage ---
            local_result = _read_local_storage_pdf(att_key, filename)
            if local_result:
                return local_result

        return None

    def lookup_best_metadata(
        self,
        *,
        title: Optional[str],
        authors: Optional[List[str]],
        year: Optional[str],
        doi: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        search_plans: List[tuple[str, str]] = []
        if doi:
            search_plans.append((doi, "everything"))
        if title:
            title_query = title
            if authors:
                title_query = f"{title} {authors[0]}"
            if year:
                title_query = f"{title_query} {year}"
            search_plans.append((title_query, "titleCreatorYear"))

        seen_keys = set()
        best_candidate: Optional[Dict[str, Any]] = None
        best_score = 0

        for query, qmode in search_plans:
            if not query.strip():
                continue
            for item in self.quick_search(query, qmode=qmode, limit=10):
                metadata = _item_to_metadata(item)
                item_type = str(metadata.get("item_type") or "")
                if item_type in {"attachment", "note"}:
                    continue
                item_key = str(metadata.get("zotero_item_key") or "")
                if item_key and item_key in seen_keys:
                    continue
                if item_key:
                    seen_keys.add(item_key)
                score = _score_metadata_candidate(
                    metadata,
                    title=title,
                    authors=authors,
                    year=year,
                    doi=doi,
                )
                if score > best_score:
                    best_score = score
                    best_candidate = metadata

        if best_candidate and best_score >= 55:
            return best_candidate
        return None

    def find_best_item_by_title_and_attachment(
        self,
        *,
        title: str,
        pdf_path: Path,
        since: Optional[int] = None,
        limit: int = 12,
    ) -> Optional[Dict[str, Any]]:
        if not title.strip():
            return None

        candidates = self.search_top_items(
            title,
            qmode="titleCreatorYear",
            limit=limit,
            since=since,
        )
        best_candidate: Optional[Dict[str, Any]] = None
        best_score = 0

        for item in candidates:
            metadata = _item_to_metadata(item)
            title_score = _score_metadata_candidate(
                metadata,
                title=title,
                authors=None,
                year=None,
                doi=None,
            )
            item_key = str(metadata.get("zotero_item_key") or "")
            attachment_score = 0
            attachment_key: Optional[str] = None
            if item_key:
                children = self.fetch_children(item_key)
                attachment_score, attachment_key = _score_attachment_candidate(
                    children,
                    pdf_path=pdf_path,
                )
            total_score = title_score + attachment_score
            if attachment_score and total_score >= best_score:
                best_score = total_score
                metadata["zotero_attachment_key"] = attachment_key
                best_candidate = metadata
            elif not best_candidate and title_score >= 80:
                metadata["zotero_attachment_key"] = attachment_key
                best_candidate = metadata

        return best_candidate

    def browse_items(
        self,
        query: str = "",
        *,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Return a list of metadata dicts for top-level library items.

        If *query* is empty, returns the most recently modified items.
        """
        if query.strip():
            items = self.search_top_items(query, qmode="titleCreatorYear", limit=limit)
        else:
            items = self._get_array(
                "/items/top",
                {
                    "format": "json",
                    "limit": str(limit),
                    "sort": "dateModified",
                    "direction": "desc",
                },
            )
        results: List[Dict[str, Any]] = []
        for item in items:
            meta = _item_to_metadata(item)
            item_type = str(meta.get("item_type") or "")
            if item_type in {"attachment", "note"}:
                continue
            results.append(meta)
        return results

    def check_duplicate(
        self,
        *,
        title: Optional[str],
        authors: Optional[List[str]] = None,
        year: Optional[str] = None,
        doi: Optional[str] = None,
        pdf_filename: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Check if a paper already exists in the Zotero library.

        Returns a metadata dict (with ``duplicate_score``) if a match is found,
        otherwise ``None``.
        """
        match = self.lookup_best_metadata(
            title=title, authors=authors, year=year, doi=doi,
        )
        if match:
            match["duplicate_score"] = "metadata"
            return match

        if pdf_filename and title:
            attachment_match = self.find_best_item_by_title_and_attachment(
                title=title,
                pdf_path=Path(pdf_filename),
            )
            if attachment_match:
                attachment_match["duplicate_score"] = "attachment"
                return attachment_match

        return None

    def create_parent_item(self, item_data: Dict[str, Any]) -> str:
        response = self._post_items([item_data])
        success = response.get("successful", {})
        if "0" not in success:
            raise ZoteroAPIError(f"Failed to create Zotero item: {response}")
        return success["0"]["key"]

    def create_attachment_item(self, attachment_data: Dict[str, Any]) -> str:
        response = self._post_items([attachment_data])
        success = response.get("successful", {})
        if "0" not in success:
            raise ZoteroAPIError(f"Failed to create Zotero attachment item: {response}")
        return success["0"]["key"]

    def upload_pdf_attachment(self, attachment_key: str, pdf_path: Path) -> None:
        pdf_bytes = pdf_path.read_bytes()
        md5_hash = hashlib.md5(pdf_bytes).hexdigest()
        mtime = int(os.path.getmtime(pdf_path) * 1000)
        content_type = mimetypes.guess_type(pdf_path.name)[0] or "application/pdf"

        form = urllib.parse.urlencode(
            {
                "md5": md5_hash,
                "filename": pdf_path.name,
                "filesize": len(pdf_bytes),
                "mtime": mtime,
                "contentType": content_type,
            }
        ).encode("utf-8")
        auth_request = urllib.request.Request(
            self._api_url(f"/items/{attachment_key}/file"),
            data=form,
            headers={
                "Zotero-API-Key": self.config.zotero_api_key,
                "Content-Type": "application/x-www-form-urlencoded",
                "If-None-Match": "*",
            },
            method="POST",
        )
        auth_payload = _json_request(auth_request, expected_statuses=[200])

        if auth_payload.get("exists") == 1:
            return

        upload_url = auth_payload.get("url")
        upload_key = auth_payload.get("uploadKey")
        prefix = auth_payload.get("prefix", "").encode("utf-8")
        suffix = auth_payload.get("suffix", "").encode("utf-8")
        upload_content_type = auth_payload.get("contentType", "application/octet-stream")
        if not upload_url or not upload_key:
            raise ZoteroAPIError(f"Incomplete Zotero upload authorization payload: {auth_payload}")

        upload_request = urllib.request.Request(
            upload_url,
            data=prefix + pdf_bytes + suffix,
            headers={"Content-Type": upload_content_type},
            method="POST",
        )
        try:
            with urllib.request.urlopen(upload_request, context=ssl.create_default_context()):
                pass
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ZoteroAPIError(f"Zotero file upload failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise ZoteroAPIError(f"Zotero file upload request failed: {exc}") from exc

        register_request = urllib.request.Request(
            self._api_url(f"/items/{attachment_key}/file"),
            data=urllib.parse.urlencode({"upload": upload_key}).encode("utf-8"),
            headers={
                "Zotero-API-Key": self.config.zotero_api_key,
                "Content-Type": "application/x-www-form-urlencoded",
                "If-None-Match": "*",
            },
            method="POST",
        )
        _json_request(register_request, expected_statuses=[204])

    def create_item_with_pdf(
        self,
        *,
        item_type: str,
        title: str,
        authors: List[str],
        year: Optional[str],
        journal: Optional[str],
        doi: Optional[str],
        url: Optional[str],
        abstract: Optional[str],
        tags: List[str],
        citekey: str,
        pdf_path: Path,
    ) -> Dict[str, str]:
        creators: List[Dict[str, str]] = []
        for author in authors:
            parts = author.strip().split()
            if len(parts) >= 2:
                creators.append(
                    {
                        "creatorType": "author",
                        "firstName": " ".join(parts[:-1]),
                        "lastName": parts[-1],
                    }
                )
            elif author.strip():
                creators.append({"creatorType": "author", "name": author.strip()})

        item_payload: Dict[str, Any] = {
            "itemType": item_type,
            "title": title,
            "creators": creators,
            "date": year or "",
            "abstractNote": abstract or "",
            "tags": [{"tag": tag} for tag in tags],
            "extra": f"Citation Key: {citekey}",
        }
        if journal:
            item_payload["publicationTitle"] = journal
        if doi:
            item_payload["DOI"] = doi
        if url:
            item_payload["url"] = url
        if self.config.zotero_collection_key:
            item_payload["collections"] = [self.config.zotero_collection_key]

        parent_key = self.create_parent_item(item_payload)
        attachment_payload = {
            "itemType": "attachment",
            "linkMode": "imported_file",
            "title": pdf_path.name,
            "parentItem": parent_key,
            "contentType": mimetypes.guess_type(pdf_path.name)[0] or "application/pdf",
            "filename": pdf_path.name,
        }
        attachment_key = self.create_attachment_item(attachment_payload)
        self.upload_pdf_attachment(attachment_key, pdf_path)
        return {"parent_key": parent_key, "attachment_key": attachment_key}


class ZoteroDesktopClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self.base_url = config.zotero_connector_url.rstrip("/")

    def _library_prefix(self) -> str:
        if self.config.zotero_library_type == "groups":
            return f"/api/groups/{self.config.zotero_user_id}"
        user_id = self.config.zotero_user_id or "0"
        return f"/api/users/{user_id}"

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        data: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        expected_statuses: Optional[List[int]] = None,
        timeout: float = 15.0,
        parse_json: bool = True,
    ) -> tuple[Any, Dict[str, str], int]:
        request_headers = {
            "X-Zotero-Connector-API-Version": ZOTERO_CONNECTOR_API_VERSION,
        }
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=request_headers,
            method=method,
        )
        expected = expected_statuses or [200]
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body_bytes = response.read()
                body = body_bytes.decode("utf-8", errors="replace")
                if response.status not in expected:
                    raise ZoteroDesktopError(
                        f"Unexpected Zotero Desktop status: {response.status} {body}"
                    )
                payload: Any
                if parse_json and body:
                    try:
                        payload = json.loads(body)
                    except json.JSONDecodeError:
                        payload = body
                elif parse_json:
                    payload = {}
                else:
                    payload = body
                return payload, {k.lower(): v for k, v in response.headers.items()}, response.status
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if expected_statuses and exc.code in expected_statuses:
                payload: Any = {}
                if parse_json and detail:
                    try:
                        payload = json.loads(detail)
                    except json.JSONDecodeError:
                        payload = detail
                elif not parse_json:
                    payload = detail
                return payload, {k.lower(): v for k, v in exc.headers.items()}, exc.code
            raise ZoteroDesktopError(f"Zotero Desktop error ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise ZoteroDesktopError(f"Zotero Desktop request failed: {exc}") from exc

    def ping(self) -> None:
        self._request("/connector/ping", parse_json=False)

    def get_targets(self) -> Dict[str, Any]:
        payload, _, _ = self._request(
            "/connector/getSelectedCollection",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        if not isinstance(payload, dict):
            raise ZoteroDesktopError(
                f"Unexpected Zotero Desktop targets payload: {type(payload).__name__}"
            )
        return payload

    def save_standalone_attachment(
        self,
        pdf_path: Path,
        *,
        session_id: str,
        title: Optional[str] = None,
        url: Optional[str] = None,
    ) -> Dict[str, Any]:
        metadata = {
            "sessionID": session_id,
            "title": title or pdf_path.name,
            "url": url or pdf_path.resolve().as_uri(),
        }
        payload, _, _ = self._request(
            "/connector/saveStandaloneAttachment",
            method="POST",
            data=pdf_path.read_bytes(),
            headers={
                "Content-Type": "application/pdf",
                "X-Metadata": json.dumps(metadata),
            },
            expected_statuses=[201],
        )
        if not isinstance(payload, dict):
            raise ZoteroDesktopError(
                f"Unexpected standalone attachment payload: {type(payload).__name__}"
            )
        return payload

    def update_session(
        self,
        *,
        session_id: str,
        target_id: str,
        tags: Optional[List[str]] = None,
        note: Optional[str] = None,
    ) -> None:
        payload = {
            "sessionID": session_id,
            "target": target_id,
            "tags": tags or [],
            "note": note or "",
        }
        self._request(
            "/connector/updateSession",
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            expected_statuses=[200],
        )

    def wait_for_recognized_item(
        self,
        session_id: str,
        *,
        timeout_seconds: float = 45.0,
        poll_interval_seconds: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        started = time.time()
        while True:
            payload, _, status = self._request(
                "/connector/getRecognizedItem",
                method="POST",
                data=json.dumps({"sessionID": session_id}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                expected_statuses=[200, 204],
            )
            if status == 200:
                if not isinstance(payload, dict):
                    raise ZoteroDesktopError(
                        f"Unexpected recognized item payload: {type(payload).__name__}"
                    )
                return payload
            if time.time() - started >= timeout_seconds:
                return None
            time.sleep(poll_interval_seconds)

    def get_local_library_version(self) -> Optional[int]:
        payload, headers, _ = self._request(
            f"{self._library_prefix()}/items/top?limit=1&format=json",
            expected_statuses=[200, 403],
        )
        if isinstance(payload, str):
            return None
        version = headers.get("last-modified-version")
        return int(version) if version and version.isdigit() else None

    def browse_local_items(
        self,
        query: str = "",
        *,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Return metadata dicts for items in the local Zotero library."""
        params = {
            "format": "json",
            "include": "data",
            "sort": "dateModified",
            "direction": "desc",
            "limit": str(limit),
        }
        if query.strip():
            params["q"] = query
            params["qmode"] = "titleCreatorYear"
        query_str = urllib.parse.urlencode(params)
        payload, _, _ = self._request(
            f"{self._library_prefix()}/items/top?{query_str}",
            expected_statuses=[200, 403],
        )
        if not isinstance(payload, list):
            return []
        results: List[Dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            meta = _item_to_metadata(item)
            item_type = str(meta.get("item_type") or "")
            if item_type in {"attachment", "note"}:
                continue
            results.append(meta)
        return results

    def search_local_top_items(
        self,
        *,
        title: str,
        since: Optional[int] = None,
        limit: int = 12,
    ) -> List[Dict[str, Any]]:
        params = {
            "format": "json",
            "include": "data",
            "q": title,
            "qmode": "titleCreatorYear",
            "sort": "dateModified",
            "direction": "desc",
            "limit": str(limit),
        }
        if since is not None:
            params["since"] = str(since)
        query = urllib.parse.urlencode(params)
        payload, _, _ = self._request(
            f"{self._library_prefix()}/items/top?{query}",
            expected_statuses=[200, 403],
        )
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def fetch_local_item_children(self, item_key: str) -> List[Dict[str, Any]]:
        payload, _, _ = self._request(
            f"{self._library_prefix()}/items/{item_key}/children?format=json&include=data&sort=dateModified&direction=desc",
            expected_statuses=[200, 403],
        )
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def get_local_item_metadata(self, item_key: str) -> Optional[Dict[str, Any]]:
        """Fetch normalised metadata for a single item via the local API."""
        try:
            payload, _, status = self._request(
                f"{self._library_prefix()}/items/{item_key}?format=json&include=data",
                expected_statuses=[200, 403, 404],
            )
            if status != 200 or not isinstance(payload, dict):
                return None
            return _item_to_metadata(payload)
        except ZoteroDesktopError:
            return None

    def get_local_item_pdf(self, item_key: str) -> Optional[tuple]:
        """Download the first PDF attachment of *item_key* via the local API.

        Returns ``(filename, pdf_bytes)`` or ``None``.
        """
        try:
            children = self.fetch_local_item_children(item_key)
        except ZoteroDesktopError:
            return None

        for child in children:
            data = child.get("data", {})
            if not isinstance(data, dict):
                continue
            content_type = str(data.get("contentType") or "")
            if "pdf" not in content_type.lower():
                continue
            att_key = child.get("key") or data.get("key")
            if not att_key:
                continue
            filename = str(data.get("filename") or "").strip() or f"{item_key}.pdf"
            try:
                file_path = self._library_prefix() + f"/items/{att_key}/file"
                request = urllib.request.Request(
                    self.base_url + file_path,
                    headers={
                        "X-Zotero-Connector-API-Version": ZOTERO_CONNECTOR_API_VERSION,
                    },
                    method="GET",
                )
                with urllib.request.urlopen(request, timeout=30) as resp:
                    pdf_bytes = resp.read()
                    if pdf_bytes and len(pdf_bytes) > 100:
                        return (filename, pdf_bytes)
            except (urllib.error.HTTPError, urllib.error.URLError, OSError):
                pass

            # Fallback: read from Zotero local storage directory
            local_result = _read_local_storage_pdf(att_key, filename)
            if local_result:
                return local_result

        return None

    def find_best_local_item_by_title_and_attachment(
        self,
        *,
        title: str,
        pdf_path: Path,
        since: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        best_candidate: Optional[Dict[str, Any]] = None
        best_score = 0
        for item in self.search_local_top_items(title=title, since=since):
            metadata = _item_to_metadata(item)
            title_score = _score_metadata_candidate(
                metadata,
                title=title,
                authors=None,
                year=None,
                doi=None,
            )
            item_key = str(metadata.get("zotero_item_key") or "")
            attachment_score = 0
            attachment_key: Optional[str] = None
            if item_key:
                children = self.fetch_local_item_children(item_key)
                attachment_score, attachment_key = _score_attachment_candidate(
                    children,
                    pdf_path=pdf_path,
                )
            total_score = title_score + attachment_score
            if attachment_score and total_score >= best_score:
                best_score = total_score
                metadata["zotero_attachment_key"] = attachment_key
                best_candidate = metadata
            elif not best_candidate and title_score >= 80:
                metadata["zotero_attachment_key"] = attachment_key
                best_candidate = metadata
        return best_candidate
