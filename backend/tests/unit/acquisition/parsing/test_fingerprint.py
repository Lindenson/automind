"""Spec 011 T081 (research R11): the structure fingerprint is stable under value changes and moves on a redesign."""

from __future__ import annotations

from pathlib import Path

from automind.acquisition.parsing import fingerprint as fp
from automind.acquisition.parsing.migrate_v1 import migrate_v1
from automind.shared.infrastructure.config.loader import load_yaml

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "html"
KM77 = migrate_v1("km77", load_yaml("site_readers.yaml")["km77"])
LABELS = fp.spec_labels(KM77)


def _html(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_same_page_same_hash():
    a = fp.structure(_html("km77_three/car_a.html"), LABELS)
    b = fp.structure(_html("km77_three/car_a.html"), LABELS)
    assert a.hash == b.hash and len(a.hash) == 16 and a.shingles


def test_values_changed_markup_same():
    a = fp.structure(_html("km77_three/car_a.html"), LABELS)
    b = fp.structure(_html("km77_three/car_b.html"), LABELS)  # another car, same template
    assert a.hash == b.hash
    assert fp.similarity(a.shingles, b.shingles) == 1.0


def test_redesign_changes_the_hash_and_similarity():
    old = fp.structure(_html("km77_three/car_a.html"), LABELS)
    new = fp.structure(_html("redesign/km77_a.html"), LABELS)
    assert old.hash != new.hash
    assert fp.similarity(old.shingles, new.shingles) < 0.6


def test_generic_fingerprint_without_labels():
    old = fp.structure(_html("km77_three/car_a.html"))
    assert old.hash == fp.structure(_html("km77_three/car_c.html")).hash
    assert fp.similarity(old.shingles, fp.structure(_html("redesign/km77_a.html")).shingles) < 0.6


def test_digit_and_hash_class_names_are_ignored():
    a = '<table class="specs t-9f3a2c"><tr class="row-1"><th>Peso</th><td>1.540 kg</td></tr></table>'
    b = '<table class="specs t-77bd01"><tr class="row-2"><th>Peso</th><td>1.615 kg</td></tr></table>'
    c = '<div class="specs"><dl><dt>Peso</dt><dd>1.540 kg</dd></dl></div>'
    fa, fb, fc = fp.structure(a, LABELS), fp.structure(b, LABELS), fp.structure(c, LABELS)
    assert fa.hash == fb.hash
    assert fa.hash != fc.hash


def test_path_stops_at_an_id():
    a = '<div id="x"><table><tr><th>Peso</th><td>1</td></tr></table></div>'
    b = '<section><div class="w"><div id="x"><table><tr><th>Peso</th><td>1</td></tr></table></div></div></section>'
    assert fp.structure(a, LABELS).hash == fp.structure(b, LABELS).hash


def test_empty_page():
    f = fp.structure("<p>nothing</p>", LABELS)
    assert f.shingles == frozenset() and fp.similarity(f.shingles, frozenset()) == 1.0
    assert fp.similarity(frozenset({"a"}), frozenset()) == 0.0
