"""Block sources: the sources each car's values were read from."""

from __future__ import annotations


def sources_block(cars: list[dict]) -> dict:
    """Accepted sources first (favourites marked, values read from tables flagged), then the pages rejected
    for another variant with their reasons (FR-012)."""
    seen: set[str] = set()
    items: list[dict] = []
    readers: dict[str, bool] = {}
    for c in cars:
        for src in c["claim_src"].values():
            readers[src["url"]] = readers.get(src["url"], False) or src.get("extracted_by") == "READER"
    for c in cars:
        for src in c["claim_src"].values():
            if src["url"] not in seen:
                seen.add(src["url"])
                item = {k: src[k] for k in ("name", "url", "type", "retrieved_at")}
                item["favourite"] = bool(src.get("favourite"))
                item["extracted_by"] = "READER" if readers.get(src["url"]) else "LLM"
                if src.get("unverified"):
                    item["unverified"] = True
                items.append(item)
    accepted = len(items)
    for c in cars:
        for src in c.get("rejected_pages", []):
            if src["url"] not in seen:
                seen.add(src["url"])
                items.append(src)
    return {"type": "sources", "title": f"Sources ({accepted})", "items": items}
