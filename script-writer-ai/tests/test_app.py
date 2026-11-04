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
