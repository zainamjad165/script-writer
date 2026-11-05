import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def fresh():
    return AppTest.from_file(APP).run(timeout=30)


def test_app_loads_clean():
    assert not fresh().exception


def test_empty_form_warns():
    at = fresh()
    at.button[0].click().run(timeout=30)
    assert any("Please fill in" in w.value for w in at.warning)


def fill(at):
    at.text_input(key="product").set_value("Steel bottle")
    at.text_input(key="audience").set_value("Students")
    at.text_area(key="qualities").set_value("Keeps cold\nLeak-proof")


def test_every_type_loads_and_generates(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    labels = ["Video script", "Social media caption", "Ad copy", "Product description"]
    for label in labels:
        with patch("llm.generate", return_value="First?\n===VERSION===\nSecond?"):
            at = fresh()
            at.selectbox(key="copy_type_label").select(label).run(timeout=30)
            assert not at.exception, label
            fill(at)
            at.button[0].click().run(timeout=30)
        assert not at.exception, label
        assert len(at.code) == 2, label


def test_form_changes_with_type():
    at = fresh()
    at.selectbox(key="copy_type_label").select("Social media caption").run(timeout=30)
    assert {c.label for c in at.checkbox} == {"Add hashtags", "Use emojis"}
    at.selectbox(key="copy_type_label").select("Product description").run(timeout=30)
    assert {c.label for c in at.checkbox} == {"Add bullet highlights"}


def test_google_ad_over_limit_shows_warning(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    bad = "HEADLINE 1: " + "x" * 40
    with patch("llm.generate", return_value=bad):
        at = fresh()
        at.selectbox(key="copy_type_label").select("Ad copy").run(timeout=30)
        at.selectbox(key="ad_platform").select("Google search ad")  # no rerun: form values apply on submit
        fill(at)
        at.button[0].click().run(timeout=30)
    assert any("40 characters" in w.value for w in at.warning)


def generate_once(monkeypatch, text="Tired of warm water?\n===VERSION===\nSecond hook?"):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    with patch("llm.generate", return_value=text):
        at = fresh()
        fill(at)
        at.button[0].click().run(timeout=30)
    assert not at.exception
    return at


def test_checks_are_shown_for_each_version(monkeypatch):
    at = generate_once(monkeypatch)
    # both versions are far shorter than the 30-second target, so both get a warning
    assert sum("target is" in w.value for w in at.warning) == 2


def test_clean_version_shows_passed_message(monkeypatch):
    good = ("Tired of warm water? " + "word " * 72).strip()
    at = generate_once(monkeypatch, good)
    assert any("Passed all automatic checks" in c.value for c in at.caption)


def test_refine_adds_a_new_version_and_keeps_the_old_one(monkeypatch):
    at = generate_once(monkeypatch)
    with patch("llm.generate", return_value="Cold water all day?"):
        at.selectbox(key="ra_0").select("Make it shorter")
        at.button(key="refine_0").click().run(timeout=30)
    assert not at.exception
    codes = [c.value for c in at.code]
    assert codes == ["Tired of warm water?", "Second hook?", "Cold water all day?"]
    assert any("Refined from version 1 (Make it shorter)" in m.value for m in at.markdown)


def test_refine_custom_needs_text(monkeypatch):
    at = generate_once(monkeypatch)
    at.selectbox(key="ra_1").select("Custom change").run(timeout=30)
    at.button(key="refine_1").click().run(timeout=30)
    assert any("describe the change" in w.value.lower() for w in at.warning)
    assert len(at.code) == 2


def test_refine_error_is_shown_and_nothing_added(monkeypatch):
    from llm import LLMError
    at = generate_once(monkeypatch)
    with patch("llm.generate", side_effect=LLMError("Free limit reached for now")):
        at.button(key="refine_0").click().run(timeout=30)
    assert any("Free limit reached" in e.value for e in at.error)
    assert len(at.code) == 2


BAD_SCRIPT = ("Tired of warm water? This bottle keeps drinks cold for 99 hours and never leaks. "
              + "word " * 20 + "Tap the link and order now.")
GOOD_SCRIPT = ("Tired of warm water? This steel bottle keeps drinks cold for 24 hours and the lid "
               "never leaks, so your bag stays dry all day long. Get free delivery today. "
               "Tap the link and order now.")


def run_with(monkeypatch, outputs, tries=None):
    """Generate once with the given sequence of AI answers."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    with patch("llm.generate", side_effect=list(outputs)) as gen:
        at = fresh()
        if tries is not None:
            at.radio(key="autofix_tries").set_value(tries)
        at.text_input(key="product").set_value("Steel bottle")
        at.text_input(key="audience").set_value("Students")
        at.text_area(key="qualities").set_value("Keeps cold for 24 hours\nLeak-proof")
        at.text_input(key="offer").set_value("Free delivery")
        at.selectbox(key="script_length").select("15 seconds")
        at.radio(key="autofix_tries")  # make sure the control exists
        at.button[0].click().run(timeout=30)
    assert not at.exception
    return at, gen


def test_autofix_on_by_default_replaces_a_failing_version(monkeypatch):
    at, gen = run_with(monkeypatch, [BAD_SCRIPT, GOOD_SCRIPT], tries=None)
    # 1 version (versions radio is 3 but the mock returns just one) + 1 fix request
    assert gen.call_count == 2
    assert [c.value for c in at.code] == [GOOD_SCRIPT]
    assert any("Auto-fixed" in m.value for m in at.markdown)
    assert any("Passed all automatic checks" in c.value for c in at.caption)


def test_autofix_off_leaves_the_draft_and_shows_warnings(monkeypatch):
    at, gen = run_with(monkeypatch, [BAD_SCRIPT], tries=0)
    assert gen.call_count == 1
    assert [c.value for c in at.code] == [BAD_SCRIPT]
    assert any("99" in w.value for w in at.warning)


def test_manual_fix_button_adds_a_fixed_version(monkeypatch):
    at, _ = run_with(monkeypatch, [BAD_SCRIPT], tries=0)
    with patch("llm.generate", return_value=GOOD_SCRIPT):
        at.button(key="fix_0").click().run(timeout=30)
    assert not at.exception
    assert [c.value for c in at.code] == [BAD_SCRIPT, GOOD_SCRIPT]
    assert any("Fixed from version 1" in m.value for m in at.markdown)


def test_manual_fix_error_is_shown(monkeypatch):
    from llm import LLMError
    at, _ = run_with(monkeypatch, [BAD_SCRIPT], tries=0)
    with patch("llm.generate", side_effect=LLMError("Free limit reached for now")):
        at.button(key="fix_0").click().run(timeout=30)
    assert any("Free limit reached" in e.value for e in at.error)
    assert len(at.code) == 1


SEP = "\n===VERSION===\n"


def test_failing_versions_are_fixed_in_a_single_extra_request(monkeypatch):
    bad2 = BAD_SCRIPT.replace("99", "77")
    fix_a, fix_b = GOOD_SCRIPT, GOOD_SCRIPT.replace("Tired of warm water?", "Warm water again?")
    at, gen = run_with(monkeypatch, [GOOD_SCRIPT + SEP + BAD_SCRIPT + SEP + bad2, fix_a + SEP + fix_b])
    assert gen.call_count == 2                        # 1 draft request + 1 batch fix, not 1 + 2
    assert [c.value for c in at.code] == [GOOD_SCRIPT, fix_a, fix_b]
    assert [w for w in at.warning if "99" in w.value or "77" in w.value] == []


def test_request_counter_and_fallback_model_are_used(monkeypatch):
    at, gen = run_with(monkeypatch, [BAD_SCRIPT, GOOD_SCRIPT])
    assert any("AI requests this session: 2" in c.value for c in at.sidebar.caption)
    assert gen.call_args.kwargs["fallback_models"] == ["gemini-flash-latest"]


def test_free_fixes_cost_no_request(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    with patch("llm.generate", side_effect=["Cool steel bottle with free delivery 😎 #cold"]) as gen:
        at = fresh()
        at.selectbox(key="copy_type_label").select("Social media caption").run(timeout=30)
        at.checkbox(key="caption_emojis").uncheck()
        at.checkbox(key="caption_hashtags").uncheck()
        at.selectbox(key="caption_length").select("Short")
        at.text_input(key="product").set_value("Steel bottle")
        at.text_input(key="audience").set_value("Students")
        at.text_area(key="qualities").set_value("Keeps cold")
        at.text_input(key="offer").set_value("Free delivery")
        at.button[0].click().run(timeout=30)
    assert not at.exception and gen.call_count == 1
    assert [c.value for c in at.code] == ["Cool steel bottle with free delivery"]
    assert any("Auto-fixed" in m.value for m in at.markdown)


SHORTER = "Warm water again? This bottle keeps drinks cold for 24 hours. Free delivery today. Order now."


def test_shorter_refine_is_not_pushed_back_to_the_length_target(monkeypatch):
    at, gen = run_with(monkeypatch, [GOOD_SCRIPT])
    with patch("llm.generate", return_value=SHORTER) as refine_gen:
        at.selectbox(key="ra_0").select("Make it shorter")
        at.button(key="refine_0").click().run(timeout=30)
    assert not at.exception
    assert refine_gen.call_count == 1                 # no auto-fix request was needed
    assert [c.value for c in at.code] == [GOOD_SCRIPT, SHORTER]
    assert not any("target is" in w.value for w in at.warning)


def test_refined_version_that_breaks_a_check_is_auto_fixed(monkeypatch):
    at, _ = run_with(monkeypatch, [GOOD_SCRIPT])
    broken = SHORTER.replace("24 hours", "99 hours")
    with patch("llm.generate", side_effect=[broken, SHORTER]) as refine_gen:
        at.selectbox(key="ra_0").select("Make it shorter")
        at.button(key="refine_0").click().run(timeout=30)
    assert refine_gen.call_count == 2
    assert [c.value for c in at.code] == [GOOD_SCRIPT, SHORTER]
    assert any("auto-fixed" in m.value for m in at.markdown)
