import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_loads_clean():
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception


def test_empty_form_warns():
    at = AppTest.from_file(APP).run(timeout=30)
    at.button[0].click().run(timeout=30)
    assert any("Please fill in" in w.value for w in at.warning)


def test_generates_versions(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    fake = "Why wait?\n===VERSION===\nTired of heat?"
    with patch("llm.generate", return_value=fake):
        at = AppTest.from_file(APP).run(timeout=30)
        at.text_input[0].set_value("Steel bottle")   # product
        at.text_input[1].set_value("Students")    # audience
        at.text_area[0].set_value("Keeps cold\nLeak-proof")
        at.button[0].click().run(timeout=30)
    assert not at.exception
    assert len(at.code) == 2
