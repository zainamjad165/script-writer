import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm import LLMError, generate


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers))
        return self.responses.pop(0)


OK = {"candidates": [{"content": {"parts": [{"text": "Hello? "}, {"text": "World"}]}}]}


def test_success_joins_parts_and_sends_key_in_header():
    s = FakeSession(FakeResp(200, OK))
    assert generate("sys", "usr", "KEY", session=s) == "Hello? World"
    url, payload, headers = s.calls[0]
    assert headers["x-goog-api-key"] == "KEY" and "KEY" not in url
    assert payload["system_instruction"]["parts"][0]["text"] == "sys"


def test_missing_key():
    with pytest.raises(LLMError, match="API key"):
        generate("s", "u", "")


@pytest.mark.parametrize("status,needle", [(429, "limit"), (403, "rejected"), (404, "model name")])
def test_friendly_errors(status, needle):
    with pytest.raises(LLMError, match=needle):
        generate("s", "u", "K", session=FakeSession(FakeResp(status, {"error": {"message": "x"}})))


def test_retry_on_server_error(monkeypatch):
    monkeypatch.setattr("llm.time.sleep", lambda s: None)
    s = FakeSession(FakeResp(503, {}), FakeResp(200, OK))
    assert generate("s", "u", "K", session=s) == "Hello? World"
    assert len(s.calls) == 2


def test_blocked_prompt():
    with pytest.raises(LLMError, match="declined"):
        generate("s", "u", "K", session=FakeSession(
            FakeResp(200, {"promptFeedback": {"blockReason": "SAFETY"}})))


def test_rate_limit_falls_back_to_the_next_model():
    s = FakeSession(FakeResp(429, {"error": {"message": "quota"}}), FakeResp(200, OK))
    assert generate("s", "u", "K", model="model-a", fallback_models=["model-b"], session=s) == "Hello? World"
    assert "model-a" in s.calls[0][0] and "model-b" in s.calls[1][0]


def test_other_errors_do_not_fall_back():
    s = FakeSession(FakeResp(403, {"error": {"message": "x"}}), FakeResp(200, OK))
    with pytest.raises(LLMError, match="rejected"):
        generate("s", "u", "K", model="a", fallback_models=["b"], session=s)
    assert len(s.calls) == 1


def test_all_models_rate_limited_raises_the_limit_message():
    s = FakeSession(FakeResp(429, {}), FakeResp(429, {}))
    with pytest.raises(LLMError, match="limit") as info:
        generate("s", "u", "K", model="a", fallback_models=["b"], session=s)
    assert info.value.rate_limited and len(s.calls) == 2


def test_duplicate_fallback_is_skipped():
    s = FakeSession(FakeResp(429, {}))
    with pytest.raises(LLMError):
        generate("s", "u", "K", model="a", fallback_models=["a"], session=s)
    assert len(s.calls) == 1
