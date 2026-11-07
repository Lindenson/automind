"""The structure checker of spec 012 (scripts/check_structure.py): one fixture tree per rule, and the ratchet."""

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_structure", Path(__file__).resolve().parents[4] / "scripts" / "check_structure.py"
)
cs = importlib.util.module_from_spec(_SPEC)
sys.modules["check_structure"] = cs
_SPEC.loader.exec_module(cs)

OWNERS = """
owners:
  chat: [chats, turns]
  acquisition: [claims]
  observability: [feedback]
reads:
  observability: ["*"]
"""


def _tree(tmp: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp / "backend/src/automind" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (tmp / "scripts").mkdir(exist_ok=True)
    (tmp / "scripts/table_owners.yaml").write_text(OWNERS, encoding="utf-8")
    return tmp


def _rules(tmp: Path) -> set[str]:
    return {v.key() for v in cs.check(tmp / "backend/src/automind", tmp / "scripts/table_owners.yaml")}


DOC_INIT = '"""Package."""\n__all__: list[str] = []\n'


def test_size_over_200_lines(tmp_path: Path) -> None:
    root = _tree(
        tmp_path, {"chat/__init__.py": DOC_INIT, "chat/big.py": "x = 1\n" * 201, "chat/ok.py": "x = 1\n" * 200}
    )
    assert _rules(root) == {"size|chat/big.py|>200"}


def test_package_needs_docstring_and_all(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"chat/__init__.py": "", "chat/m.py": "", "chat/sub/m.py": ""})
    assert _rules(root) == {
        "pkgdoc|chat/__init__.py|docstring",
        "pkgdoc|chat/__init__.py|__all__",
        "pkgdoc|chat/sub/__init__.py|missing",
    }


def test_public_after_private_is_reported_by_name(tmp_path: Path) -> None:
    code = "def a(): pass\ndef _h(): pass\ndef b(): pass\nclass C: pass\ndef __dunder(): pass\n"
    root = _tree(tmp_path, {"chat/__init__.py": DOC_INIT, "chat/m.py": code})
    assert _rules(root) == {"order|chat/m.py|b", "order|chat/m.py|C"}


def test_regex_and_word_table_inside_function(tmp_path: Path) -> None:
    code = (
        "import re\nNAME = re.compile('x')\n"
        "def f(s):\n    return re.search(r'\\d+', s)\n"
        "def g(s, p):\n    return re.search(p, s)\n"  # a pattern from elsewhere is fine
        "def h(s):\n    return s in {'a','b','c','d','e','f','g','h'}\n"
        "def k(s):\n    return s in {'a','b'}\n"
        "def r(v):\n    return {'a': v.a, 'b': v.b, 'c': v.c, 'd': v.d, 'e': v.e, 'f': v.f, 'g': v.g, 'h': v.h}\n"
    )
    root = _tree(tmp_path, {"chat/__init__.py": DOC_INIT, "chat/m.py": code})
    assert _rules(root) == {"regex|chat/m.py|f", "table|chat/m.py|h"}


def test_function_node_usecase_and_service_lengths(tmp_path: Path) -> None:
    body = lambda n: "def {name}(s, r):\n" + "    x = 1\n" * n  # noqa: E731
    files = {
        "chat/__init__.py": DOC_INIT,
        "chat/m.py": body(79).format(name="ok") + body(80).format(name="long"),
        "chat/dialog/__init__.py": DOC_INIT,
        "chat/dialog/nodes/__init__.py": DOC_INIT,
        "chat/dialog/nodes/n.py": body(29).format(name="small")
        + body(30).format(name="fat")
        + body(40).format(name="_helper"),
        "chat/application/__init__.py": DOC_INIT,
        "chat/application/usecases/__init__.py": DOC_INIT,
        "chat/application/usecases/u.py": "class U:\n    def run(self):\n" + "        x = 1\n" * 30,
        "chat/application/services/__init__.py": DOC_INIT,
        "chat/application/services/s/__init__.py": DOC_INIT,
        "chat/application/services/s/service.py": "class S:\n    def run(self):\n" + "        x = 1\n" * 60,
    }
    lengths = {k for k in _rules(_tree(tmp_path, files)) if k.split("|")[0] in ("func", "node")}
    assert lengths == {
        "func|chat/m.py|long",
        "node|chat/dialog/nodes/n.py|fat",
        "node|chat/application/usecases/u.py|U.run",
        "node|chat/application/services/s/service.py|S.run",
    }


def test_sql_to_another_areas_table(tmp_path: Path) -> None:
    files = {
        "chat/__init__.py": DOC_INIT,
        "chat/m.py": "Q = 'SELECT id FROM turns'\nR = 'select x from claims where y = 1'\n",
        "acquisition/__init__.py": DOC_INIT,
        "acquisition/m.py": "Q = 'SELECT * FROM feedback JOIN claims ON 1=1'\n",
        "observability/__init__.py": DOC_INIT,
        "observability/m.py": "Q = 'SELECT * FROM turns JOIN claims ON 1=1'\n",  # reads everything
    }
    assert _rules(_tree(tmp_path, files)) == {
        "sql|chat/m.py|claims@acquisition",
        "sql|acquisition/m.py|feedback@observability",
    }


def test_legacy_paths_map_to_areas() -> None:
    assert cs.area_of("insight/repo.py") == "observability"
    assert cs.area_of("domain/intake.py") == "chat"
    assert cs.area_of("acquisition/api.py") == "acquisition"
    assert cs.area_of("chat/domain/x.py") == "chat"


def test_ratchet_new_and_fixed_entries_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(
        tmp_path, {"chat/__init__.py": DOC_INIT, "chat/m.py": "def a(): pass\ndef _h(): pass\ndef b(): pass\n"}
    )
    assert cs.main(["--root", str(root), "--write-baseline"]) == 0
    assert cs.main(["--root", str(root)]) == 0
    (root / "backend/src/automind/chat/m.py").write_text("def a(): pass\ndef b(): pass\ndef _h(): pass\n")
    assert cs.main(["--root", str(root)]) == 1  # fixed but still listed
    assert "FIXED order|chat/m.py|b" in capsys.readouterr().out
    (root / "backend/src/automind/chat/m.py").write_text("def _h(): pass\ndef a(): pass\ndef b(): pass\n")
    assert cs.main(["--root", str(root)]) == 1  # a new violation
    assert "NEW   order|chat/m.py|a" in capsys.readouterr().out


def test_exceptions_file_silences_a_rule_for_a_path(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"chat/__init__.py": DOC_INIT, "chat/words.py": "x = 1\n" * 500})
    (root / "scripts/structure_exceptions.txt").write_text("size|chat/words.py|vocabulary table, data only\n")
    (root / "scripts/structure_baseline.txt").write_text("")
    assert cs.main(["--root", str(root)]) == 0


# --- API rules (scripts/structure_api.py), from the antipattern usecases/challenge.py ---------------------------

LAYER = {"chat/__init__.py": DOC_INIT, "chat/application/__init__.py": DOC_INIT}


def test_public_api_of_a_layer_is_typed_without_any_and_documented(tmp_path: Path) -> None:
    code = (
        "from typing import Any\n"
        "def loose(x, y: int) -> int:\n    '''Doc.'''\n    return y\n"
        "def vague(x: Any) -> dict[str, Any]:\n    '''Doc.'''\n    return {}\n"
        "def silent(x: int) -> int:\n    return x\n"
        "class Service:\n"
        "    def __init__(self, store: Any) -> None:\n        self.store = store\n"
        "    def run(self) -> int:\n        '''Doc.'''\n        return 1\n"
        "def _private(x):\n    return x\n"
    )
    root = _tree(tmp_path, {**LAYER, "chat/application/m.py": code})
    assert _rules(root) == {
        "untyped|chat/application/m.py|loose",
        "any|chat/application/m.py|vague",
        "doc|chat/application/m.py|silent",
        "doc|chat/application/m.py|Service",
        "any|chat/application/m.py|Service.__init__",
    }


def test_public_function_over_40_lines_but_only_in_a_layer(tmp_path: Path) -> None:
    long = "def long() -> int:\n    '''Doc.'''\n" + "    x = 1\n" * 38 + "    return x\n"
    root = _tree(tmp_path, {**LAYER, "chat/application/m.py": long, "chat/web.py": long})
    assert _rules(root) == {"public|chat/application/m.py|long"}


def test_type_ignore_and_lazy_import_in_any_layer(tmp_path: Path) -> None:
    code = "x: int = 'a'  # type: ignore\ndef f():\n    import os  # noqa\n    return os.sep  # type: ignore[attr]\n"
    root = _tree(tmp_path, {"chat/__init__.py": DOC_INIT, "chat/m.py": code})
    assert _rules(root) == {"ignore|chat/m.py|<module>", "ignore|chat/m.py|f", "lazy|chat/m.py|f"}


def test_each_ignore_imports_line_is_an_exemption(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"chat/__init__.py": DOC_INIT})
    (root / "backend/.importlinter").write_text(
        "[importlinter:contract:app]\nname = x\nignore_imports =\n    # why\n    a.b -> c.d\n    a.e -> sqlalchemy\n"
        "[importlinter:contract:other]\nname = y\n"
    )
    assert _rules(root) == {"exempt|.importlinter|app:a.b -> c.d", "exempt|.importlinter|app:a.e -> sqlalchemy"}


SQL_AND_DB = "from sqlalchemy import text\nfrom automind.shared.infrastructure import db\n"


def test_storage_outside_infrastructure_in_any_package(tmp_path: Path) -> None:
    root = _tree(tmp_path, {
        "acquisition/__init__.py": DOC_INIT,
        "acquisition/reputation/__init__.py": DOC_INIT,
        "acquisition/reputation/baseline.py": SQL_AND_DB,
        "acquisition/reputation/infrastructure/__init__.py": DOC_INIT,
        "acquisition/reputation/infrastructure/store.py": "from sqlalchemy import select\n",
        "delivery/__init__.py": DOC_INIT,
        "delivery/web/__init__.py": DOC_INIT,
        "delivery/web/app.py": "from automind.shared.infrastructure import db\n",
    })  # fmt: skip
    assert _rules(root) == {
        "storage|acquisition/reputation/baseline.py|sqlalchemy",
        "storage|acquisition/reputation/baseline.py|automind.shared.infrastructure.db",
    }
