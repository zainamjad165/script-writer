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
