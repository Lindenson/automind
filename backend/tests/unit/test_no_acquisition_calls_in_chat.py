"""The chat orders data through `acquisition.api` and never searches, fetches, parses or extracts itself (spec 011
T037, FR-005, constitution XIII). An AST scan of the chat's code for the engine's calls."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "automind"
CHAT = ("chat",)

# Files still doing acquisition work while the strangler moved it into the engine: emptied by T051 (SC-004).
ALLOWED_DURING_STRANGLER: set[str] = set()

ROLES = {"extractor", "relevance", "validator", "lineup", "versions", "terms_reader"}


def _hit(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr == "page_store":
        return "page_store"
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
    owner = ast.unparse(f.value) if isinstance(f, ast.Attribute) else ""
    if name == "search" and (owner == "search" or owner.endswith(".search") or owner.endswith("searcher")):
        return f"{owner}.search("
    if name == "get" and (owner == "pages" or owner.endswith(".pages")):
        return ".pages.get("
    if name == "read" and owner.endswith("readers"):
        return "readers.read("
    if name == "extract" and owner in ("extraction", "ex"):
        return f"{owner}.extract("
    if name == "fetch_raw":
        return "fetch_raw("
    if name == "structured" and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in ROLES:
        return f'structured("{node.args[0].value}")'
    return None


def _scan() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for pkg in CHAT:
        for path in sorted((SRC / pkg).rglob("*.py")):
            rel = path.relative_to(SRC).as_posix()
            if rel == "application/ports.py":  # the port's own definition of `page_store`
                continue
            hits = [f"{h} (line {n.lineno})" for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                    if (h := _hit(n)) is not None]  # fmt: skip
            if hits:
                out[rel] = hits
    return out


def test_the_chat_makes_no_acquisition_calls():
    found = _scan()
    new = {f: h for f, h in found.items() if f not in ALLOWED_DURING_STRANGLER}
    assert not new, f"acquisition calls in the chat (order data through acquisition.api instead): {new}"


def test_the_strangler_is_finished():
    assert not ALLOWED_DURING_STRANGLER


def test_the_strangler_allow_list_only_names_files_that_still_need_it():
    found = _scan()
    stale = sorted(f for f in ALLOWED_DURING_STRANGLER if f not in found)
    assert not stale, f"remove from ALLOWED_DURING_STRANGLER (no acquisition call left): {stale}"


def test_the_scan_finds_the_engine_calls():
    code = (
        "async def f(ports, ex, llm):\n"
        "    await ports.search.search('q')\n    ports.page_store\n    await ports.pages.get('u')\n"
        "    ports.readers.read(1, {})\n    await ex.extract(1)\n    await fetch_raw('u')\n"
        "    await llm.structured('extractor', 1, 2, 3)\n    import re; re.search('a', 'b')\n"
        "    await llm.structured('resolver', 1, 2, 3)\n"
    )
    hits = [h for n in ast.walk(ast.parse(code)) if (h := _hit(n)) is not None]
    assert len(hits) == 7, hits
