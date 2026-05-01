from __future__ import annotations

import ssl
import urllib.error
import urllib.parse
import urllib.request


class ObsidianWriteError(RuntimeError):
    pass


def write_note(base_url: str, api_key: str, note_path: str, content: str) -> None:
    encoded_path = urllib.parse.quote(note_path)
    url = base_url.rstrip("/") + "/vault/" + encoded_path
    request = urllib.request.Request(
        url,
        data=content.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "text/markdown; charset=utf-8",
        },
        method="PUT",
    )
    context = ssl._create_unverified_context() if base_url.startswith("https://") else None
    try:
        with urllib.request.urlopen(request, context=context):
            return
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ObsidianWriteError(f"Obsidian REST API error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise ObsidianWriteError(f"Obsidian REST API request failed: {exc}") from exc
