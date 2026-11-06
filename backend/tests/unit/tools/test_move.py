"""The move codemod of spec 012 (scripts/refactor/move.py): references are rewritten, files move with git."""

import importlib.util
import subprocess
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "refactor_move", Path(__file__).resolve().parents[4] / "scripts" / "refactor" / "move.py"
)
mv = importlib.util.module_from_spec(_SPEC)
sys.modules["refactor_move"] = mv
_SPEC.loader.exec_module(mv)

MOVES = {
    "automind.domain.intake": "automind.chat.domain.intake",
    "automind.insight": "automind.observability",
    "automind.application.compose": "automind.chat.application.services.report.compose",
}


def test_dotted_names_imports_and_patch_strings() -> None:
    text = (
        "import automind.domain.intake\n"
        "from automind.domain.intake import Fit, rank_lineup\n"
        "from automind.insight.domain import clusters\n"
        'mock.patch("automind.application.compose.load_car")\n'
        "from automind.domain.intake_steps import x  # a different module\n"
    )
    assert mv.rewrite(text, MOVES) == (
        "import automind.chat.domain.intake\n"
        "from automind.chat.domain.intake import Fit, rank_lineup\n"
        "from automind.observability.domain import clusters\n"
        'mock.patch("automind.chat.application.services.report.compose.load_car")\n'
        "from automind.domain.intake_steps import x  # a different module\n"
    )


def test_from_parent_import_of_a_moved_module_is_split_by_target() -> None:
    text = (
        "from automind.domain import casefile, intake as ik\n"
        "from automind.application import (\n    compose,\n    ports,\n)\n"
    )
    assert mv.rewrite(text, MOVES) == (
        "from automind.domain import casefile\nfrom automind.chat.domain import intake as ik\n"
        "from automind.chat.application.services.report import compose\nfrom automind.application import ports\n"
    )


def test_paths_compose_commands_and_baseline_entries() -> None:
    text = "python -m automind.insight.loop\nsee backend/src/automind/domain/intake.py\n"
    assert mv.rewrite(text, MOVES) == (
        "python -m automind.observability.loop\nsee backend/src/automind/chat/domain/intake.py\n"
    )
    base = "size|domain/intake.py|>400\norder|insight/infrastructure/repo.py|x\norder|domain/intake_steps.py|y\n"
    assert mv.rewrite(base, MOVES, is_baseline=True) == (
        "size|chat/domain/intake.py|>400\norder|observability/infrastructure/repo.py|x\norder|domain/intake_steps.py|y\n"
    )


def test_relative_imports_become_absolute() -> None:
    text = "from .casefile import CaseFile\nfrom . import units\nfrom ..infrastructure import db\n"
    assert mv.absolutize(text, "automind.domain.intake") == (
        "from automind.domain.casefile import CaseFile\nfrom automind.domain import units\n"
        "from automind.infrastructure import db\n"
    )
    assert mv.absolutize("from .x import y\n", "automind.insight.__init__") == "from automind.insight.x import y\n"


def test_run_moves_files_with_git_and_creates_packages(tmp_path: Path) -> None:
    src = tmp_path / "backend/src/automind"
    (src / "domain").mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "domain/__init__.py").write_text("")
    (src / "domain/intake.py").write_text("from .casefile import X\n")
    (src / "domain/casefile.py").write_text("X = 1\n")
    (src / "user.py").write_text("from automind.domain import intake\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    mv.run(tmp_path, {"automind.domain.intake": "automind.chat.domain.intake"})
    assert (src / "chat/domain/intake.py").read_text() == "from automind.domain.casefile import X\n"
    assert (src / "chat/__init__.py").exists() and (src / "chat/domain/__init__.py").exists()
    assert not (src / "domain/intake.py").exists()
    assert (src / "user.py").read_text() == "from automind.chat.domain import intake\n"


def test_a_module_renamed_inside_its_package_is_imported_under_its_old_name() -> None:
    moves = {"automind.acquisition.replay.__main__": "automind.acquisition.replay.command"}
    text = "from automind.acquisition.replay import __main__ as cli\nfrom automind.acquisition.replay import run\n"
    assert mv.rewrite(text, moves) == (
        "from automind.acquisition.replay import command as cli\nfrom automind.acquisition.replay import run\n"
    )
