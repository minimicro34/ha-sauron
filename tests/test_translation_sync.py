"""Ensure source and English translation keys stay synchronized."""

import json
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "sauron"


def _keys(value, prefix=()):
    if isinstance(value, dict):
        return {key for name, child in value.items() for key in _keys(child, (*prefix, name))}
    return {prefix}


def test_english_translations_match_source_keys():
    source = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    assert _keys(english) == _keys(source)
    assert "enable_dated_statistics" not in json.dumps(source)
    assert "enable_dated_statistics" not in json.dumps(english)
    assert english["entity"]["sensor"]["previous_week_m3"]["name"]
    assert english["entity"]["sensor"]["last_successful_poll"]["name"]
