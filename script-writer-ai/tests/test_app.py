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
