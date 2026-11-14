import os
from pathlib import Path
from unittest.mock import patch

import pytest

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
DOTENV = Path(APP).with_name(".env")


@pytest.fixture
def real_looking_dotenv():
    """Temporarily create a .env like a developer's, then put things back."""
    before = DOTENV.read_text() if DOTENV.exists() else None
    DOTENV.write_text("GEMINI_API_KEY=real-key\nDISCORD_WEBHOOK_URL=https://discord.invalid/api/webhooks/1/abc\n")
    yield
    if before is None:
        DOTENV.unlink()
    else:
        DOTENV.write_text(before)


def test_a_developers_dotenv_is_ignored_by_the_tests(real_looking_dotenv):
    assert os.environ["DISCORD_WEBHOOK_URL"] == "" and os.environ["GEMINI_API_KEY"] == ""
    with patch("llm.generate", return_value="Why wait? Cold all day. Tap the link."):
        at = AppTest.from_file(APP).run(timeout=30)
        at.text_input(key="product").set_value("Steel bottle")
        at.text_input(key="audience").set_value("Students")
        at.text_area(key="qualities").set_value("Keeps cold")
        at.button[0].click().run(timeout=30)
    assert not at.exception                                   # no Discord post was attempted
    assert not any("sent to the developer" in i.value for i in at.sidebar.info)


def test_real_network_requests_are_blocked_in_tests():
    import requests
    with pytest.raises(AssertionError, match="real network request"):
        requests.post("https://example.com", json={})
