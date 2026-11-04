import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompt import (COPY_TYPES, REFINE_ACTIONS, VERSION_SEPARATOR, Brief, build_prompt,
                    build_refine_prompt, limit_warnings, load_examples, load_rules,
                    parse_versions, pick_examples, refine_instruction)


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


def test_script_prompt_contains_brief_and_rules():
    system, user = build_prompt(make_brief(language="Roman Urdu", length="15 seconds"),
                                rules="RULE-X", examples=[])
    assert "RULE-X" in system and VERSION_SEPARATOR in system
    assert "Steel bottle" in user and "Roman Urdu" in user
    assert "35-45 words" in user and "Free delivery" in user


def test_no_offer_is_not_invented():
    _, user = build_prompt(make_brief(offer=""), rules="r", examples=[])
    assert "do not invent" in user


def test_every_copy_type_builds_a_prompt():
    for key, ct in COPY_TYPES.items():
        for platform in ct.platforms:
            system, user = build_prompt(
                make_brief(copy_type=key, platform=platform, length=ct.default_length,
                           keywords="candles"), examples=[])
            assert ct.label in user
            assert "OUTPUT FORMAT" in system and len(system) > 200


def test_caption_toggles():
    on = build_prompt(make_brief(copy_type="caption", toggles={"hashtags": True, "emojis": False}),
                      rules="r", examples=[])[1]
    assert "hashtags" in on and "Do not use any emojis" in on
    off = build_prompt(make_brief(copy_type="caption", toggles={"hashtags": False}),
                       rules="r", examples=[])[1]
    assert "Do not use any hashtags" in off


def test_google_ad_format_has_limits():
    system, _ = build_prompt(make_brief(copy_type="ad", platform="Google search ad"),
                             rules="r", examples=[])
    assert "HARD LIMIT 30" in system and "HARD LIMIT 90" in system


def test_keywords_only_for_types_that_support_them():
    assert "Keywords to include" in build_prompt(
        make_brief(copy_type="product", keywords="steel bottle"), rules="r", examples=[])[1]
    assert "Keywords to include" not in build_prompt(
        make_brief(copy_type="script", keywords="steel bottle"), rules="r", examples=[])[1]


def test_unknown_type_falls_back_to_script():
    _, user = build_prompt(make_brief(copy_type="nonsense"), rules="r", examples=[])
    assert "Video script" in user


def test_rules_files_exist_for_every_type():
    for key in COPY_TYPES:
        assert load_rules(key), key
    assert "HOOK" in load_rules("script")


def test_examples_are_filtered_by_type_and_language():
    exs = load_examples()
    assert {e.get("type", "script") for e in exs} == set(COPY_TYPES)
    pick = pick_examples(make_brief(copy_type="caption", language="Roman Urdu"), exs, limit=1)
    assert pick[0]["type"] == "caption" and pick[0]["language"] == "Roman Urdu"
    assert all(e.get("type", "script") == "ad"
               for e in pick_examples(make_brief(copy_type="ad"), exs))


def test_every_type_has_a_starter_example():
    exs = load_examples()
    for key in COPY_TYPES:
        assert any(e.get("type", "script") == key for e in exs), key


def test_starter_google_ad_respects_limits():
    for e in load_examples():
        assert limit_warnings(e["script"], e.get("type", "script"), e.get("platform", "")) == []


def test_limit_warnings_catch_overlong_lines():
    text = "HEADLINE 1: " + "x" * 31 + "\nDESCRIPTION 1: ok\nHEADLINE 2: fine"
    w = limit_warnings(text, "ad", "Google search ad")
    assert len(w) == 1 and "31 characters" in w[0]
    assert limit_warnings(text, "ad", "Facebook / Instagram ad") == []


def test_bad_example_file_is_skipped(tmp_path):
    (tmp_path / "bad.json").write_text("{not json")
    (tmp_path / "good.json").write_text(json.dumps(
        [{"brief": {"product": "x"}, "output": "hello?"}]))
    assert len(load_examples(tmp_path)) == 1


def test_parse_versions():
    text = f"one\n{VERSION_SEPARATOR}\ntwo\n{VERSION_SEPARATOR}\n"
    assert parse_versions(text) == ["one", "two"]
    assert parse_versions("just one") == ["just one"]
    assert parse_versions("  ") == []


def test_refine_instruction_variants():
    assert "shorter" in refine_instruction("Make it shorter")
    assert "Funny" in refine_instruction("Change the tone", tone="Funny")
    assert refine_instruction("Change the tone") == ""            # no tone chosen yet
    assert refine_instruction("Custom change", custom="  add warranty ") == "add warranty"
    assert refine_instruction("Custom change", custom="  ") == ""
    assert refine_instruction("nonsense") == ""
    assert set(REFINE_ACTIONS) >= {"Make it shorter", "Try a different hook", "Custom change"}


def test_refine_prompt_has_original_change_brief_and_format():
    for key, ct in COPY_TYPES.items():
        b = make_brief(copy_type=key, platform=ct.platforms[0], length=ct.default_length)
        system, user = build_refine_prompt(b, "ORIGINAL TEXT?", "make it punchier", rules="RULE-X")
        assert "RULE-X" in system and "ONE revised version" in system
        assert ct.format_for(ct.platforms[0]) in system
        assert "ORIGINAL TEXT?" in user and "make it punchier" in user
        assert "Steel bottle" in user and "Free delivery" in user
        assert VERSION_SEPARATOR not in system
