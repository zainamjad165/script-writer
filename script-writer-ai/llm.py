"""Tiny client for the Google Gemini API (free tier works with a free key)."""
from __future__ import annotations

import time

import requests

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# "-latest" aliases keep working when Google retires specific model versions.
DEFAULT_MODEL = "gemini-flash-lite-latest"


class LLMError(Exception):
    """Raised with a message that is safe and friendly to show to the user."""


def _friendly_error(status: int, body: dict | None) -> str:
    msg = ""
    if isinstance(body, dict):
        msg = str(body.get("error", {}).get("message", ""))
    if status == 429:
        return ("Free limit reached for now (too many requests). Wait a minute and try again. "
                "If it keeps happening, you've used today's free quota - try again tomorrow "
                "or switch the model in the sidebar.")
    if status in (400, 401, 403):
        if "API key" in msg or status in (401, 403):
            return "The API key was rejected. Check that GEMINI_API_KEY is correct."
        return f"The request was rejected: {msg or 'bad request'}"
    if status == 404:
        return ("That model name was not found (Google renames models often). "
                "Change the model in the sidebar, e.g. gemini-flash-latest.")
    if status >= 500:
        return "Google's server is busy right now. Please try again in a moment."
    return f"Unexpected error ({status}): {msg}"


def generate(
    system: str,
    user: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.9,
    timeout: int = 60,
    session: requests.Session | None = None,
) -> str:
    if not api_key:
        raise LLMError("No API key found. Add GEMINI_API_KEY (see README).")
    http = session or requests
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096},
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    url = API_URL.format(model=model.strip() or DEFAULT_MODEL)

    last_error = "Unknown error"
    for attempt in range(2):  # one retry on temporary server errors
        try:
            resp = http.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.RequestException:
            raise LLMError("Could not reach Google. Check your internet connection.")
        try:
            body = resp.json()
        except ValueError:
            body = None
        if resp.status_code == 200:
            return _extract_text(body)
        last_error = _friendly_error(resp.status_code, body)
        if resp.status_code >= 500 and attempt == 0:
            time.sleep(2)
            continue
        break
    raise LLMError(last_error)


def _extract_text(body: dict | None) -> str:
    if not isinstance(body, dict):
        raise LLMError("Empty response from the AI. Try again.")
    candidates = body.get("candidates") or []
    if not candidates:
        reason = body.get("promptFeedback", {}).get("blockReason")
        if reason:
            raise LLMError("The AI declined this request. Try rewording the product details.")
        raise LLMError("The AI returned nothing. Try again.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise LLMError("The AI returned an empty answer. Try again.")
    return text
