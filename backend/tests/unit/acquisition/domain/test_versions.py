"""Version identifiers of readers, prompts and specs (spec 011 T006, research R2)."""

import pytest

from automind.acquisition.domain import versions


def test_reader_key():
    assert versions.reader_key("km77", 1) == "km77@v1"
    assert versions.reader_key("site:km77", 3) == "km77@v3"


def test_prompt_key_from_header():
    assert versions.prompt_key_from_header("<!-- prompt: extract_specs v3 (web reader, no tools) -->") == (
        "extract_specs",
        3,
    )
    assert versions.prompt_key_from_header("You extract facts.") is None


def test_prompt_key_with_and_without_header():
    assert versions.prompt_key("<!-- prompt: extract_specs v2 (x) -->\nbody", "extractor") == "extract_specs@v2"
    assert versions.prompt_key("no header here", "extract_specs") == "extract_specs@legacy"


def test_prompt_key_of_name_and_version():
    assert versions.prompt_version_key("extract_specs", "v3") == "extract_specs@v3"
    assert versions.prompt_version_key("relevance", None) == "relevance@legacy"


def test_spec_hash_is_stable_under_key_order():
    a = {"reader": "km77", "version": 1, "fields": [{"attribute": "max_power", "label": "potencia"}]}
    b = {"fields": [{"label": "potencia", "attribute": "max_power"}], "version": 1, "reader": "km77"}
    assert versions.spec_hash(a) == versions.spec_hash(b)
    assert len(versions.spec_hash(a)) == 12
    assert versions.spec_hash(a) != versions.spec_hash({**a, "version": 2})


def test_parse_key():
    assert versions.parse_key("km77@v12") == ("km77", 12)
    assert versions.parse_key("extract_specs@v3") == ("extract_specs", 3)


@pytest.mark.parametrize("bad", ["km77", "km77@12", "@v1", "km77@vx", "extract_specs@legacy"])
def test_parse_key_rejects_non_versions(bad):
    with pytest.raises(ValueError):
        versions.parse_key(bad)
