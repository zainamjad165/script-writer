"""Keep the test suite away from real settings and real services.

The app reads a local .env file, so without this a developer's real Discord webhook or API key
would be picked up by the tests and real messages would be sent. Every setting is pinned to a
safe value, and any real network request or Discord post fails loudly instead of happening.
"""
import pytest
import requests


@pytest.fixture(autouse=True)
def isolated_from_real_services(monkeypatch):
    # The app only fills a setting from .env when it is not set at all, so an empty value wins.
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("APP_PASSWORD", "")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-flash-latest")

    def blocked(*args, **kwargs):
        raise AssertionError("A test tried to make a real network request.")

    # Tests that need a fake post replace these themselves; anything else is stopped here.
    monkeypatch.setattr(requests, "post", blocked)
    monkeypatch.setattr("feedback.post_discord_async", blocked)
