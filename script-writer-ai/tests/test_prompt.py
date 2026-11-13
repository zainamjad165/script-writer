import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompt import (COPY_TYPES, REFINE_ACTIONS, VERSION_SEPARATOR, Brief, build_prompt,
                    build_batch_fix_prompt, build_refine_prompt, limit_warnings, load_examples, load_rules,
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


def test_batch_fix_prompt_lists_each_version_with_its_problems():
    b = make_brief(copy_type="script", platform="TikTok", length="15 seconds")
    system, user = build_batch_fix_prompt(
        b, [("First text?", ["Problem A."]), ("Second text?", ["Problem B.", "Problem C."])],
        keep="Make it shorter", rules="RULE-X")
    assert "exactly 2 revised version(s)" in system and VERSION_SEPARATOR in system
    assert "RULE-X" in system and "Do not undo that change" in system
    assert user.index("VERSION 1:") < user.index("First text?") < user.index("VERSION 2:")
    assert "- Problem A." in user and "- Problem C." in user
    assert "Steel bottle" in user                     # brief included for reference


def test_prompt_demands_every_key_quality_in_every_version():
    system, user = build_prompt(make_brief(), rules="r", examples=[])
    assert "EVERY version must include ALL" in system and "never in which key qualities" in system
    assert "ALL must appear" in user


def test_extra_notes_are_marked_secondary():
    _, user = build_prompt(make_brief(extra="weighs 200g"), rules="r", examples=[])
    assert "use only if there is space" in user and "weighs 200g" in user


def test_rules_files_carry_the_expert_feedback():
    assert "ALL the key qualities" in load_rules("script")
    assert "never in which key qualities" in load_rules("script")


def test_include_all_qualities_refine_action():
    assert "EVERY key quality" in refine_instruction("Include all key qualities")


def test_length_hint_labels():
    from prompt import get_copy_type, length_hint
    assert length_hint(get_copy_type("script"), "30 seconds") == "30 seconds (~70-85 words)"
    assert length_hint(get_copy_type("caption"), "Short") == "Short (up to ~30 words)"
    assert length_hint(get_copy_type("ad"), "Medium") == "Medium (~40-60 words)"


def test_shot_by_shot_format_is_requested_only_when_chosen():
    shot = build_prompt(make_brief(format="Shot-by-shot (timestamps)", length="30 seconds"),
                        rules="r", examples=[])
    assert "VISUAL:" in shot[0] and "ON-SCREEN TEXT:" in shot[0] and "0-3s" in shot[0]
    assert "Format: Shot-by-shot (timestamps)" in shot[1]
    plain = build_prompt(make_brief(), rules="r", examples=[])
    assert "VISUAL:" not in plain[0] and "Format: Voiceover only" in plain[1]


def test_each_version_gets_its_own_angle_and_formats_have_different_angles():
    system, _ = build_prompt(make_brief(versions=3), rules="r", examples=[])
    assert "Version 1:" in system and "Version 2:" in system and "Version 3:" in system
    assert "do not just swap synonyms" in system
    shot, _ = build_prompt(make_brief(versions=3, format="Shot-by-shot (timestamps)"), rules="r", examples=[])
    assert "Challenge or demo" in shot and "Challenge or demo" not in system
    one, _ = build_prompt(make_brief(versions=1), rules="r", examples=[])
    assert "Version 1:" in one and "Version 2:" not in one


def test_every_copy_type_has_angles():
    for ct in COPY_TYPES.values():
        assert len(ct.angles_for("")) == 3 or ct.key == "script"


def test_pain_points_shots_and_cta_reach_the_prompt_only_where_they_apply():
    b = make_brief(pain_points=["Warm water", " "], shots="gym floor, pouring ice",
                   cta="Tap the link in bio", format="Shot-by-shot (timestamps)")
    _, user = build_prompt(b, rules="r", examples=[])
    assert "Problems it solves" in user and "- Warm water" in user
    assert "gym floor, pouring ice" in user and "Tap the link in bio" in user
    _, voice = build_prompt(make_brief(shots="gym floor", cta="Tap the link"), rules="r", examples=[])
    assert "gym floor" not in voice                       # shots only matter for shot lists
    _, product = build_prompt(make_brief(copy_type="product", cta="Tap the link"), rules="r", examples=[])
    assert "Tap the link" not in product                  # product descriptions have no CTA box


def test_examples_are_matched_to_the_chosen_format():
    exs = load_examples()
    shot = pick_examples(make_brief(format="Shot-by-shot (timestamps)"), exs)
    assert shot and all(e.get("format") == "Shot-by-shot (timestamps)" for e in shot)
    voice = pick_examples(make_brief(), exs)
    assert voice and all(e.get("format", "Voiceover only") == "Voiceover only" for e in voice)


def test_shot_example_brief_details_are_shown_to_the_model():
    system, _ = build_prompt(make_brief(format="Shot-by-shot (timestamps)", language="English"),
                             rules="r")
    assert "problems it solves=" in system and "shots available=" in system


def test_new_refine_action_and_tone():
    from prompt import TONES
    assert "person talking" in refine_instruction("Sound less like a spec sheet")
    assert "High-energy / punchy" in TONES


def test_rules_carry_the_professional_feedback():
    general = load_rules("script")
    assert "No cliché openings" in general and "Never read a price out loud" in general
    assert "Shot-by-shot" in general and "ON-SCREEN TEXT" in general
