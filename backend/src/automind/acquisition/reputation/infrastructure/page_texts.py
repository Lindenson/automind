"""The visible text of stored pages (snapshots) for the blame rules, and of any stored page body."""

from __future__ import annotations

import html
import re

from automind.acquisition.snapshots import store

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)  # "<script>…</script>", "<p class=x>"


def page_text_of(raw: bytes) -> str:
    """Visible text of a stored page body (tags, scripts and styles removed)."""
    text = raw.decode("utf-8", errors="replace")
    return " ".join(html.unescape(_TAG.sub(" ", text)).split())


class SnapshotPages:
    """Pages from the snapshot store."""

    async def snapshot_text(self, snapshot_id: str) -> str | None:
        """The page's visible text, None when the snapshot is gone."""
        try:
            raw, _ = await store.load(snapshot_id)
        except KeyError:
            return None
        return page_text_of(raw)
