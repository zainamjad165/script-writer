import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from streamlit.testing.v1 import AppTest

from llm import LLMError

APP = str(Path(__file__).resolve().parent.parent / "app.py")
SEP = "\n===VERSION===\n"

# 15-second voiceover texts for the standard test brief below
GOOD_SCRIPT = ("Why settle for warm water? This steel bottle keeps drinks cold for 24 hours and the lid "
               "never leaks, so your bag stays dry all day long. Get free delivery today. "
               "Tap the link and order now.")
GOOD2 = GOOD_SCRIPT.replace("Why settle for warm water?", "Warm water at lunch?")
BAD_SCRIPT = ("Why settle for warm water? This bottle keeps drinks cold for 99 hours and never leaks. "
              + "word " * 20 + "Tap the link and order now.")
BAD2 = BAD_SCRIPT.replace("99", "77")
SHORTER = "Warm water again? Cold for 24 hours, leak-proof, free delivery today. Order now."


def fresh():
    return AppTest.from_file(APP).run(timeout=30)


def fill(at):
    at.text_input(key="product").set_value("Steel bottle")
    at.text_input(key="audience").set_value("Students")
    at.text_area(key="qualities").set_value("Keeps cold for 24 hours\nLeak-proof")
    at.text_input(key="offer").set_value("Free delivery")


def generate(monkeypatch, outputs, tones=None, copy_type=None, length="15 seconds"):
    """Fill the standard brief, click the button, and answer the AI requests in order."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    with patch("llm.generate", side_effect=list(outputs)) as gen:
        at = fresh()
        if copy_type:
            at.selectbox(key="copy_type_label").select(copy_type).run(timeout=30)
        fill(at)
        if copy_type is None:
            at.selectbox(key="script_length").select(length)
        if tones is not None:
            at.multiselect(key="tones").set_value(tones)
        at.button[0].click().run(timeout=30)
    assert not at.exception
    return at, gen


def codes(at):
    return [c.value for c in at.code]


def has_text(elements, needle):
    return any(needle in e.value for e in elements)


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------
def test_app_loads_clean():
    assert not fresh().exception


def test_empty_form_warns():
    at = fresh()
    at.button[0].click().run(timeout=30)
    assert has_text(at.warning, "Please fill in")


def test_the_sidebar_has_no_settings_any_more():
    at = fresh()
    sidebar = at.sidebar
    assert not sidebar.selectbox and not sidebar.slider and not sidebar.radio and not sidebar.text_input
    assert not any("AI model" in str(w.label) for w in at.text_input)


def test_form_changes_with_type():
    at = fresh()
    at.selectbox(key="copy_type_label").select("Social media caption").run(timeout=30)
    assert {c.label for c in at.checkbox} == {"Add hashtags", "Use emojis"}
    at.selectbox(key="copy_type_label").select("Product description").run(timeout=30)
    assert {c.label for c in at.checkbox} == {"Add bullet highlights"}


def test_length_picker_shows_word_targets():
    assert "30 seconds (~70-85 words)" in fresh().selectbox(key="script_length").options


def test_every_type_loads_and_generates_and_shows_one_version(monkeypatch):
    for label in ("Video script", "Social media caption", "Ad copy", "Product description"):
        at, _ = generate(monkeypatch, ["First?" + SEP + "Second?"], copy_type=label)
        assert len(at.code) == 1, label


def test_google_ad_over_limit_shows_warning(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    with patch("llm.generate", return_value="HEADLINE 1: " + "x" * 40):
        at = fresh()
        at.selectbox(key="copy_type_label").select("Ad copy").run(timeout=30)
        at.selectbox(key="ad_platform").select("Google search ad")   # no rerun: form values apply on submit
        fill(at)
        at.button[0].click().run(timeout=30)
    assert has_text(at.warning, "40 characters")


# ---------------------------------------------------------------------------
# Fixed settings: 3 versions, creativity 0.8, the model chosen automatically
# ---------------------------------------------------------------------------
def test_the_ai_is_always_asked_for_three_versions_at_creativity_0_8(monkeypatch):
    _, gen = generate(monkeypatch, [GOOD_SCRIPT])
    system, user = gen.call_args.args[0], gen.call_args.args[1]
    assert "exactly 3 version(s)" in system and "Version 3:" in system
    assert gen.call_args.kwargs["temperature"] == 0.8
    assert gen.call_args.kwargs["model"] == "gemini-flash-lite-latest"
    assert gen.call_args.kwargs["fallback_models"] == ["gemini-flash-latest"]


def test_a_missing_model_is_replaced_automatically_and_remembered(monkeypatch):
    import llm
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    asked = []

    def fake_one(system, user, api_key, model, temperature, timeout, http):
        asked.append(model)
        if model == "gemini-flash-lite-latest":
            raise LLMError("gone", model_missing=True)
        return GOOD_SCRIPT

    monkeypatch.setattr(llm, "_generate_one", fake_one)
    for _ in range(2):
        at = fresh()
        fill(at)
        at.selectbox(key="script_length").select("15 seconds")
        at.button[0].click().run(timeout=30)
        assert not at.exception and codes(at) == [GOOD_SCRIPT]
    # first click tried the missing model then the backup; the second click went straight to the backup
    assert asked == ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-flash-latest"]


# ---------------------------------------------------------------------------
# Best of three
# ---------------------------------------------------------------------------
def test_only_the_best_of_the_three_versions_is_shown(monkeypatch):
    at, gen = generate(monkeypatch, [BAD_SCRIPT + SEP + GOOD_SCRIPT + SEP + BAD2])
    assert gen.call_count == 1                         # one request wrote all three
    assert codes(at) == [GOOD_SCRIPT]
    assert has_text(at.markdown, "Best of 3")
    assert has_text(at.caption, "Passed all automatic checks")
    assert at.button(key="alt_0").label == "Show another option (2 left)"


def test_show_another_option_reveals_the_next_best_for_free(monkeypatch):
    at, gen = generate(monkeypatch, [BAD_SCRIPT + SEP + GOOD_SCRIPT + SEP + GOOD2])
    assert codes(at) == [GOOD_SCRIPT]                   # GOOD2 ties it, so the AI's order decides
    at.button(key="alt_0").click().run(timeout=30)
    assert codes(at) == [GOOD_SCRIPT, GOOD2]
    assert at.button(key="alt_0").label == "Show another option (1 left)"
    at.button(key="alt_0").click().run(timeout=30)
    assert codes(at) == [GOOD_SCRIPT, GOOD2, BAD_SCRIPT]
    assert not any(b.key == "alt_0" for b in at.button)  # nothing left to reveal
    assert gen.call_count == 1                          # revealing never costs an AI request
    assert has_text(at.markdown, "Another option from version 1")


def test_a_single_version_has_no_other_options_button(monkeypatch):
    at, _ = generate(monkeypatch, [GOOD_SCRIPT])
    assert not any(b.key == "alt_0" for b in at.button)
    assert has_text(at.markdown, "Best of 1")


def test_checks_are_shown_for_the_version_that_is_displayed(monkeypatch):
    at, _ = generate(monkeypatch, [BAD_SCRIPT])
    assert has_text(at.warning, "99") and has_text(at.warning, "offer")
    assert at.button(key="fix_0")


# ---------------------------------------------------------------------------
# One or several tones
# ---------------------------------------------------------------------------
def test_two_tones_give_one_best_version_each_with_one_request_each(monkeypatch):
    at, gen = generate(monkeypatch, [GOOD_SCRIPT, GOOD2], tones=["Friendly", "Funny"])
    assert gen.call_count == 2
    assert codes(at) == [GOOD_SCRIPT, GOOD2]
    assert has_text(at.markdown, "Friendly · Best of 1") and has_text(at.markdown, "Funny · Best of 1")
    users = [c.args[1] for c in gen.call_args_list]
    assert "Tone: Friendly" in users[0] and "Tone: Funny" in users[1] and "genuinely funny" in users[1]
    assert has_text(at.sidebar.caption, "AI requests this session: 2")


def test_each_tone_keeps_its_own_brief_when_refined(monkeypatch):
    at, _ = generate(monkeypatch, [GOOD_SCRIPT, GOOD2], tones=["Friendly", "Funny"])
    with patch("llm.generate", return_value=SHORTER) as refine_gen:
        at.selectbox(key="ra_1").select("Make it shorter")
        at.button(key="refine_1").click().run(timeout=30)
    assert "Tone: Funny" in refine_gen.call_args.args[1]
    assert has_text(at.markdown, "Refined from version 2")


def test_picking_no_tone_asks_for_one(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    with patch("llm.generate", side_effect=[]) as gen:
        at = fresh()
        fill(at)
        at.multiselect(key="tones").set_value([])
        at.button[0].click().run(timeout=30)
    assert has_text(at.warning, "tone") and gen.call_count == 0 and not at.code


def test_the_tone_picker_defaults_to_one_tone_and_allows_up_to_four():
    at = fresh()
    picker = at.multiselect(key="tones")
    assert picker.value == ["Friendly"]
    assert "up to 4" in picker.proto.help


def test_a_failure_on_a_later_tone_keeps_the_tones_that_worked(monkeypatch):
    at, gen = generate(monkeypatch, [GOOD_SCRIPT, LLMError("Free limit reached for now")],
                       tones=["Friendly", "Funny"])
    assert codes(at) == [GOOD_SCRIPT]
    assert has_text(at.warning, "Couldn't write every tone") and has_text(at.warning, "Funny: Free limit")


def test_if_every_request_fails_the_error_is_shown_and_nothing_else(monkeypatch):
    at, _ = generate(monkeypatch, [LLMError("Free limit reached for now")])
    assert has_text(at.error, "Free limit reached") and not at.code


# ---------------------------------------------------------------------------
# Free fixes, manual fix, refine
# ---------------------------------------------------------------------------
def test_free_fixes_cost_no_request(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    with patch("llm.generate", side_effect=["Cool steel bottle with free delivery 😎 #cold — wow"]) as gen:
        at = fresh()
        at.selectbox(key="copy_type_label").select("Social media caption").run(timeout=30)
        at.checkbox(key="caption_emojis").uncheck()
        at.checkbox(key="caption_hashtags").uncheck()
        at.selectbox(key="caption_length").select("Short")
        fill(at)
        at.button[0].click().run(timeout=30)
    assert not at.exception and gen.call_count == 1
    assert codes(at) == ["Cool steel bottle with free delivery, wow"]


def test_manual_fix_button_adds_a_fixed_version(monkeypatch):
    at, _ = generate(monkeypatch, [BAD_SCRIPT])
    with patch("llm.generate", return_value=GOOD_SCRIPT):
        at.button(key="fix_0").click().run(timeout=30)
    assert not at.exception
    assert codes(at) == [BAD_SCRIPT, GOOD_SCRIPT]
    assert has_text(at.markdown, "Fixed from version 1")


def test_manual_fix_error_is_shown(monkeypatch):
    at, _ = generate(monkeypatch, [BAD_SCRIPT])
    with patch("llm.generate", side_effect=LLMError("Free limit reached for now")):
        at.button(key="fix_0").click().run(timeout=30)
    assert has_text(at.error, "Free limit reached") and len(at.code) == 1


def test_refine_adds_a_new_version_and_keeps_the_old_one(monkeypatch):
    at, _ = generate(monkeypatch, [GOOD_SCRIPT])
    with patch("llm.generate", return_value="Cold water all day?"):
        at.selectbox(key="ra_0").select("Make it shorter")
        at.button(key="refine_0").click().run(timeout=30)
    assert not at.exception
    assert codes(at) == [GOOD_SCRIPT, "Cold water all day?"]
    assert has_text(at.markdown, "Refined from version 1 (Make it shorter)")


def test_shorter_refine_is_not_pushed_back_to_the_length_target(monkeypatch):
    at, _ = generate(monkeypatch, [GOOD_SCRIPT])
    with patch("llm.generate", return_value=SHORTER) as refine_gen:
        at.selectbox(key="ra_0").select("Make it shorter")
        at.button(key="refine_0").click().run(timeout=30)
    assert refine_gen.call_count == 1
    assert codes(at) == [GOOD_SCRIPT, SHORTER]
    assert not has_text(at.warning, "target is")


def test_a_refined_version_that_breaks_a_check_is_left_for_the_fix_button(monkeypatch):
    at, _ = generate(monkeypatch, [GOOD_SCRIPT])
    broken = SHORTER.replace("24 hours", "99 hours")
    with patch("llm.generate", side_effect=[broken]) as refine_gen:
        at.selectbox(key="ra_0").select("Make it shorter")
        at.button(key="refine_0").click().run(timeout=30)
    assert refine_gen.call_count == 1                  # no automatic fixing any more
    assert codes(at) == [GOOD_SCRIPT, broken] and has_text(at.warning, "99")
    assert at.button(key="fix_1")


def test_refine_custom_needs_text(monkeypatch):
    at, _ = generate(monkeypatch, [GOOD_SCRIPT])
    at.selectbox(key="ra_0").select("Custom change").run(timeout=30)
    at.button(key="refine_0").click().run(timeout=30)
    assert has_text(at.warning, "describe the change") and len(at.code) == 1


def test_refine_error_is_shown_and_nothing_added(monkeypatch):
    at, _ = generate(monkeypatch, [GOOD_SCRIPT])
    with patch("llm.generate", side_effect=LLMError("Free limit reached for now")):
        at.button(key="refine_0").click().run(timeout=30)
    assert has_text(at.error, "Free limit reached") and len(at.code) == 1


def test_include_all_qualities_refine_action_sends_its_instruction(monkeypatch):
    at, _ = generate(monkeypatch, [GOOD_SCRIPT])
    with patch("llm.generate", return_value=GOOD_SCRIPT) as refine_gen:
        at.selectbox(key="ra_0").select("Include all key qualities")
        at.button(key="refine_0").click().run(timeout=30)
    assert not at.exception and "EVERY key quality" in refine_gen.call_args.args[1]


def test_request_counter_counts_requests_not_versions(monkeypatch):
    at, _ = generate(monkeypatch, [BAD_SCRIPT + SEP + GOOD_SCRIPT + SEP + BAD2])
    assert has_text(at.sidebar.caption, "AI requests this session: 1")


def test_script_form_has_format_shots_cta_and_pain_points_but_other_types_do_not_have_format():
    at = fresh()
    assert at.selectbox(key="script_format").options == ["Voiceover only", "Shot-by-shot (timestamps)"]
    assert at.text_area(key="script_shots") and at.text_input(key="cta") and at.text_area(key="pain_points")
    at.selectbox(key="copy_type_label").select("Product description").run(timeout=30)
    assert all(sb.key != "product_format" for sb in at.selectbox)
    assert not any(t.key == "cta" for t in at.text_input)      # no call-to-action box for products


SHOT_LIST = """0-3s
VISUAL: Runner shakes the bottle over a gym bag.
VOICEOVER: If your bottle can't survive this, bin it.
ON-SCREEN TEXT: TEST YOUR BOTTLE

3-12s
VISUAL: Ice cubes clink in the bottle after a hot day.
VOICEOVER: Still ice cold after twenty-four hours, and it never leaks into your bag, even upside down.
ON-SCREEN TEXT: 24 HOURS COLD

12-21s
VISUAL: One thumb flips the cap open mid-set.
VOICEOVER: Keep your rest short and your hands free, because the cap opens with one thumb and stays out of your face.
ON-SCREEN TEXT: ONE-HAND CAP

21-30s
VISUAL: Athlete walks out with the bottle, product shot.
VOICEOVER: Grab yours while the launch batch lasts. Free delivery is on, so tap the link in bio.
ON-SCREEN TEXT: FREE DELIVERY"""


def test_shot_by_shot_request_reaches_the_ai_and_shows_spoken_words(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    with patch("llm.generate", return_value=SHOT_LIST) as gen:
        at = fresh()
        at.selectbox(key="script_format").select("Shot-by-shot (timestamps)")
        at.text_input(key="product").set_value("Steel bottle")
        at.text_input(key="audience").set_value("Athletes")
        at.text_area(key="qualities").set_value("Keeps cold for 24 hours\nNever leaks in a bag")
        at.text_input(key="offer").set_value("Free delivery")
        at.text_area(key="pain_points").set_value("Warm water mid-workout\nLeaky bags")
        at.text_area(key="script_shots").set_value("gym floor, ice cubes")
        at.text_input(key="cta").set_value("Tap the link in bio")
        at.button[0].click().run(timeout=30)
    assert not at.exception
    system, user = gen.call_args_list[0].args[0], gen.call_args_list[0].args[1]
    assert "VISUAL:" in system and "Format: Shot-by-shot (timestamps)" in user
    assert "Warm water mid-workout" in user and "gym floor, ice cubes" in user
    assert "Tap the link in bio" in user
    assert has_text(at.markdown, "spoken words")
    assert codes(at) == [SHOT_LIST]


# ---------------------------------------------------------------------------
# One example product in every hint
# ---------------------------------------------------------------------------
FOREIGN_PRODUCT_WORDS = ["bottle", "gym", "water", "earbuds", "headset", "candle", "laptop", "achar", "fan "]


def hints(at):
    return [w.placeholder for w in list(at.text_input) + list(at.text_area) if w.placeholder]


def test_every_hint_in_every_copy_type_describes_the_same_example_product():
    for label in ("Video script", "Social media caption", "Ad copy", "Product description"):
        at = fresh()
        at.selectbox(key="copy_type_label").select(label).run(timeout=30)
        found = hints(at)
        assert len(found) >= 7, (label, found)
        for hint in found:
            assert not any(word in hint.lower() for word in FOREIGN_PRODUCT_WORDS), (label, hint)
        assert any("kurta" in h.lower() for h in found), label


def test_script_form_hints_cover_every_script_only_box_too():
    at = fresh()
    keyed = {w.key: w.placeholder for w in list(at.text_input) + list(at.text_area)}
    for key in ("product", "audience", "qualities", "offer", "pain_points", "cta", "script_shots", "avoid", "extra"):
        assert keyed.get(key), key


# ---------------------------------------------------------------------------
# Everything the tool does is sent to Discord
# ---------------------------------------------------------------------------
def with_webhook(monkeypatch, url="https://hook.example/abc"):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    # An empty value (not a deleted variable) so the app's .env loader cannot fill it in again.
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", url)
    sent = []
    monkeypatch.setattr("feedback.post_discord_async", lambda u, msgs: sent.append((u, list(msgs))))
    return sent


def generate_with_everything_filled(outputs, tones=None):
    with patch("llm.generate", side_effect=list(outputs)):
        at = fresh()
        at.text_input(key="product").set_value("Cotton kurta")
        at.text_input(key="audience").set_value("Young men in Pakistan")
        at.text_area(key="qualities").set_value("Keeps cold for 24 hours\nLeak-proof")
        at.text_input(key="offer").set_value("Free delivery")
        at.text_area(key="pain_points").set_value("Sticky shirts in summer\nShrinking after one wash")
        at.text_input(key="cta").set_value("Tap the link in bio")
        at.text_area(key="script_shots").set_value("market walk, fabric close-up")
        at.text_input(key="avoid").set_value("cheap")
        at.text_area(key="extra").set_value("Available in navy")
        at.selectbox(key="script_length").select("15 seconds")
        if tones is not None:
            at.multiselect(key="tones").set_value(tones)
        at.button[0].click().run(timeout=30)
    assert not at.exception
    return at


def test_each_generation_sends_the_full_brief_and_all_three_versions_shown_and_hidden(monkeypatch):
    sent = with_webhook(monkeypatch)
    generate_with_everything_filled([BAD_SCRIPT + SEP + GOOD_SCRIPT + SEP + BAD2])
    assert len(sent) == 1 and sent[0][0] == "https://hook.example/abc"
    text = "\n".join(sent[0][1])
    for needle in ("Cotton kurta", "Young men in Pakistan", "Keeps cold for 24 hours", "Leak-proof", "Free delivery",
                   "Sticky shirts in summer", "Shrinking after one wash", "Tap the link in bio",
                   "market walk, fabric close-up", "cheap", "Available in navy", "15 seconds",
                   "Language: English", "Tone: Friendly", "Settings: best of 3, creativity 0.8",
                   "Shown to the user (best of 3)", "Hidden option 1", "Hidden option 2",
                   GOOD_SCRIPT[:40], BAD_SCRIPT[:40], BAD2[:40]):
        assert needle in text, needle
    assert "AI request #" in text


def test_every_tone_is_logged_separately(monkeypatch):
    sent = with_webhook(monkeypatch)
    generate_with_everything_filled([GOOD_SCRIPT, GOOD2], tones=["Friendly", "Funny"])
    assert len(sent) == 2
    assert "Tone: Friendly" in "\n".join(sent[0][1]) and "Tone: Funny" in "\n".join(sent[1][1])


def test_asking_for_another_option_is_logged(monkeypatch):
    sent = with_webhook(monkeypatch)
    at = generate_with_everything_filled([BAD_SCRIPT + SEP + GOOD_SCRIPT + SEP + GOOD2])
    at.button(key="alt_0").click().run(timeout=30)
    assert len(sent) == 2 and "asked for another option (from version 1, Friendly)" in "\n".join(sent[1][1])


def test_no_webhook_means_nothing_is_sent_and_no_notice_is_shown(monkeypatch):
    sent = with_webhook(monkeypatch, url="")
    at = generate_with_everything_filled([GOOD_SCRIPT])
    assert sent == []
    assert not any("sent to the developer" in i.value for i in at.sidebar.info)


def test_the_user_is_told_their_input_is_sent_when_logging_is_on(monkeypatch):
    with_webhook(monkeypatch)
    at = fresh()
    assert any("sent to the developer" in i.value for i in at.sidebar.info)


def test_refine_and_fix_are_logged_too(monkeypatch):
    sent = with_webhook(monkeypatch)
    at = generate_with_everything_filled([BAD_SCRIPT])
    assert len(sent) == 1
    with patch("llm.generate", return_value=GOOD_SCRIPT):
        at.selectbox(key="ra_0").select("Make it shorter")
        at.button(key="refine_0").click().run(timeout=30)
    assert len(sent) == 2 and "Refined from version 1 (Make it shorter)" in "\n".join(sent[1][1])
    with patch("llm.generate", return_value=GOOD_SCRIPT):
        at.button(key="fix_0").click().run(timeout=30)
    assert len(sent) == 3 and "Fixed from version 1" in "\n".join(sent[2][1])


def test_failed_generations_are_not_logged(monkeypatch):
    sent = with_webhook(monkeypatch)
    with patch("llm.generate", side_effect=LLMError("Free limit reached for now")):
        at = fresh()
        at.text_input(key="product").set_value("Cotton kurta")
        at.text_input(key="audience").set_value("Young men")
        at.text_area(key="qualities").set_value("Soft cotton")
        at.button[0].click().run(timeout=30)
    assert sent == [] and has_text(at.error, "Free limit reached")
