import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompt import (Brief, VERSION_SEPARATOR, build_prompt, load_examples,
                    parse_versions, pick_examples)


def make_brief(**kw):
    base = dict(product="Steel bottle", audience="Students",
                qualities=["Keeps cold", " ", "Leak-proof"], offer="Free delivery")
    base.update(kw)
    return Brief(**base)


def test_missing_fields():
    assert make_brief(product="", qualities=[" "]).missing() == ["product", "qualities"]
    assert make_brief().missing() == []


def test_blank_qualities_dropped():
    assert make_brief().qualities_clean == ["Keeps cold", "Leak-proof"]


def test_prompt_contains_brief_and_rules():
    system, user = build_prompt(make_brief(language="Roman Urdu", length="15 seconds"),
                                rules="RULE-X", examples=[])
    assert "RULE-X" in system
    assert VERSION_SEPARATOR in system
    assert "Steel bottle" in user and "Roman Urdu" in user
    assert "35-45 words" in user
    assert "Free delivery" in user


def test_no_offer_is_not_invented():
    _, user = build_prompt(make_brief(offer=""), rules="r", examples=[])
    assert "do not invent" in user


def test_starter_examples_load_and_prefer_language():
    exs = load_examples()
    assert len(exs) >= 3
    picked = pick_examples(make_brief(language="Roman Urdu"), exs, limit=1)
    assert picked[0]["language"] == "Roman Urdu"


def test_bad_example_file_is_skipped(tmp_path):
    (tmp_path / "bad.json").write_text("{not json")
    (tmp_path / "good.json").write_text(json.dumps(
        [{"brief": {"product": "x"}, "script": "hello?"}]))
    assert len(load_examples(tmp_path)) == 1


def test_parse_versions():
    text = f"one\n{VERSION_SEPARATOR}\ntwo\n{VERSION_SEPARATOR}\n"
    assert parse_versions(text) == ["one", "two"]
    assert parse_versions("just one") == ["just one"]
    assert parse_versions("  ") == []
