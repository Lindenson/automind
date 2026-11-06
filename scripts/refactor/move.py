#!/usr/bin/env python3
"""Move modules and packages and rewrite every reference to them (spec 012 research R5). Move-only: no logic edits.

    move.py MAP.yaml [--root DIR] [--dry-run] [--no-format]

MAP.yaml maps dotted names under `automind`, old → new, for modules or whole packages:

    moves:
      automind.domain.intake: automind.chat.domain.intake
      automind.insight: automind.observability

What it does, in order:
1. relative imports in the Python files it will touch become absolute (a moved module's `from .x import y` would
   otherwise point elsewhere);
2. `git mv` of every file (parent packages get an `__init__.py` placeholder that S3c fills);
3. rewrites references in Python, YAML, TOML, INI, shell, Dockerfile, compose and Markdown files:
   - dotted names `automind.old.mod[.rest]` (imports, `mock.patch("…")` strings, `python -m …`, `.importlinter`);
   - `from automind.old import mod` where `mod` itself moved (split per target parent);
   - file paths `automind/old/mod.py` and the structure baseline's `old/mod.py` entries;
4. `ruff check --fix --select I` and `ruff format` on the changed Python files.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

TEXT_GLOBS = ("backend/src/**/*.py", "backend/tests/**/*.py", "backend/alembic/**/*.py", "backend/.importlinter",
              "backend/pyproject.toml", "backend/config/**/*.yaml", "scripts/**/*", "docs/**/*.md", "README.md",
              "Dockerfile", "docker-compose*.yml", "deploy/**/*")  # fmt: skip
SRC = Path("backend/src")
BASELINE = Path("scripts/structure_baseline.txt")
PLACEHOLDER = '"""Package created by the spec 012 tree move; its documentation comes in step S3c."""\n\n__all__: list[str] = []\n'
_FROM_IMPORT = re.compile(r"^(?P<ind>[ \t]*)from\s+(?P<mod>automind(?:\.\w+)*)\s+import\s+(?P<names>\([^)]*\)|[^\n#]+)",
                          re.M)  # fmt: skip
_RELATIVE = re.compile(r"^(?P<ind>[ \t]*)from\s+(?P<dots>\.+)(?P<mod>[\w.]*)\s+import\s", re.M)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("map", type=Path)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-format", action="store_true")
    a = ap.parse_args(argv)
    moves = load_moves(a.map)
    changed = run(a.root, moves, dry_run=a.dry_run)
    print(f"{len(moves)} moves, {len(changed)} files rewritten" + (" (dry run)" if a.dry_run else ""))
    if not a.dry_run and not a.no_format:
        _format(a.root, [p for p in changed if p.suffix == ".py"])
    return 0


def load_moves(path: Path) -> dict[str, str]:
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    moves = {str(k): str(v) for k, v in (d.get("moves") or {}).items()}
    for old, new in moves.items():
        if not (old.startswith("automind.") and new.startswith("automind.")):
            raise SystemExit(f"both names must start with 'automind.': {old} -> {new}")
    return moves


def run(root: Path, moves: dict[str, str], *, dry_run: bool = False) -> list[Path]:
    files = _text_files(root)
    sources = {old: _source_path(root, old) for old in moves}
    missing = [old for old, p in sources.items() if p is None]
    if missing:
        raise SystemExit(f"not found: {', '.join(missing)}")
    changed: set[Path] = set()
    for f in files:
        if f.suffix == ".py" and _under(f, root / SRC):
            text = f.read_text(encoding="utf-8")
            new = absolutize(text, _module_of(root, f))
            if new != text:
                changed.add(f)
                if not dry_run:
                    f.write_text(new, encoding="utf-8")
    if not dry_run:
        for old, new in moves.items():
            _git_mv(root, sources[old], new)  # type: ignore[arg-type]
        files = _text_files(root)
    for f in files:
        text = f.read_text(encoding="utf-8") if not dry_run or f.exists() else ""
        new = rewrite(text, moves, is_baseline=f.resolve() == (root / BASELINE).resolve())
        if new != text:
            changed.add(f)
            if not dry_run:
                f.write_text(new, encoding="utf-8")
    return sorted(changed)


def rewrite(text: str, moves: dict[str, str], *, is_baseline: bool = False) -> str:
    """Every reference to a moved name, in one text."""
    text = _rewrite_from_imports(text, moves)
    for old, new in sorted(moves.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<![\w.]){re.escape(old)}(?![\w])", new, text)
        old_path, new_path = old.replace(".", "/"), new.replace(".", "/")
        text = re.sub(rf"(?<![\w]){re.escape(old_path)}(?=(\.py|/|\b))", new_path, text)
        if is_baseline:
            o, n = old_path.removeprefix("automind/"), new_path.removeprefix("automind/")
            text = re.sub(rf"(?m)(^\w+\|){re.escape(o)}(?=(\.py\||/))", rf"\g<1>{n}", text)
    return text


def absolutize(text: str, module: str) -> str:
    """`from .x import y` → `from automind.pkg.x import y` for a module named `module` (dotted)."""
    package = module.removesuffix(".__init__") if module.endswith(".__init__") else module.rsplit(".", 1)[0]

    def fix(m: re.Match[str]) -> str:
        base = package.split(".")
        up = len(m["dots"]) - 1
        if up:
            base = base[:-up]
        target = ".".join(base + ([m["mod"]] if m["mod"] else []))
        return f"{m['ind']}from {target} import "

    return _RELATIVE.sub(fix, text)


# --- helpers -----------------------------------------------------------------------------------------------------


def _rewrite_from_imports(text: str, moves: dict[str, str]) -> str:
    def fix(m: re.Match[str]) -> str:
        mod, raw = m["mod"], m["names"]
        inner = raw.strip()[1:-1] if raw.strip().startswith("(") else raw
        names = [n.strip() for n in inner.replace("\n", " ").split(",") if n.strip()]
        groups: dict[str, list[str]] = {}
        for item in names:
            name = item.split(" as ")[0].strip()
            full = f"{mod}.{name}"
            target = _moved(full, moves)
            parent = target.rsplit(".", 1)[0] if target else mod
            if target and target.rsplit(".", 1)[1] != name:
                item = f"{target.rsplit('.', 1)[1]} as {item.split(' as ')[1] if ' as ' in item else name}"
            groups.setdefault(parent, []).append(item)
        if list(groups) == [mod]:
            return m.group(0)
        return "\n".join(f"{m['ind']}from {p} import {', '.join(items)}" for p, items in groups.items())

    return _FROM_IMPORT.sub(fix, text)


def _moved(full: str, moves: dict[str, str]) -> str | None:
    for old, new in sorted(moves.items(), key=lambda kv: -len(kv[0])):
        if full == old:
            return new
        if full.startswith(old + "."):
            return new + full[len(old):]
    return None


def _source_path(root: Path, dotted: str) -> Path | None:
    base = root / SRC / Path(*dotted.split("."))
    if base.is_dir():
        return base
    f = base.with_suffix(".py")
    return f if f.exists() else None


def _git_mv(root: Path, src: Path, new: str) -> None:
    dst = root / SRC / Path(*new.split("."))
    if src.suffix == ".py":
        dst = dst.with_suffix(".py")
    dst.parent.mkdir(parents=True, exist_ok=True)
    pkg = dst.parent
    while pkg != root / SRC and not (pkg / "__init__.py").exists():
        (pkg / "__init__.py").write_text(PLACEHOLDER, encoding="utf-8")
        subprocess.run(["git", "add", str(pkg / "__init__.py")], cwd=root, check=True)
        pkg = pkg.parent
    subprocess.run(["git", "mv", str(src), str(dst)], cwd=root, check=True)


def _text_files(root: Path) -> list[Path]:
    out: set[Path] = set()
    for g in TEXT_GLOBS:
        out.update(p for p in root.glob(g) if p.is_file() and not {"__pycache__", ".venv", "refactor", "tools", "moves"} & set(p.parts))
    return sorted(out)


def _module_of(root: Path, f: Path) -> str:
    return ".".join(f.relative_to(root / SRC).with_suffix("").parts)


def _under(f: Path, d: Path) -> bool:
    try:
        f.relative_to(d)
        return True
    except ValueError:
        return False


def _format(root: Path, files: list[Path]) -> None:
    if not files:
        return
    args = [str(p.relative_to(root / "backend")) for p in files if p.exists() and p.is_relative_to(root / "backend")]
    subprocess.run(["uv", "run", "ruff", "check", "--fix", "--select", "I", *args], cwd=root / "backend", check=False)
    subprocess.run(["uv", "run", "ruff", "format", *args], cwd=root / "backend", check=False)


if __name__ == "__main__":
    sys.exit(main())
