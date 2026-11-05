"""Tiny client for the Google Gemini API (free tier works with a free key)."""
from __future__ import annotations

import time

import requests

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# "-latest" aliases keep working when Google retires specific model versions.
DEFAULT_MODEL = "gemini-flash-lite-latest"
# Tried automatically when the main model hits its free limit. As far as I know,
# free-tier limits are counted per model, so a second model has its own allowance.
DEFAULT_FALLBACK_MODELS = ("gemini-flash-latest",)


class LLMError(Exception):
    """Raised with a message that is safe and friendly to show to the user."""

    def __init__(self, message: str, rate_limited: bool = False):
        super().__init__(message)
        self.rate_limited = rate_limited


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


def _generate_one(system, user, api_key, model, temperature, timeout, http) -> str:
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096},
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    url = API_URL.format(model=model.strip() or DEFAULT_MODEL)

    last_error, status = "Unknown error", 0
    for attempt in range(2):  # one retry on temporary server errors
        try:
            resp = http.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.RequestException:
            raise LLMError("Could not reach Google. Check your internet connection.")
        try:
            body = resp.json()
        except ValueError:
            body = None
        status = resp.status_code
        if status == 200:
            return _extract_text(body)
        last_error = _friendly_error(status, body)
        if status >= 500 and attempt == 0:
            time.sleep(2)
            continue
        break
    raise LLMError(last_error, rate_limited=(status == 429))


def generate(
    system: str,
    user: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.9,
    timeout: int = 60,
    session: requests.Session | None = None,
    fallback_models: tuple | list = (),
) -> str:
    if not api_key:
        raise LLMError("No API key found. Add GEMINI_API_KEY (see README).")
    http = session or requests
    models = [model] + [m for m in fallback_models if m and m != model]
    last: LLMError | None = None
    for name in models:
        try:
            return _generate_one(system, user, api_key, name, temperature, timeout, http)
        except LLMError as e:
            last = e
            if not e.rate_limited:   # only a free-limit error is worth trying another model for
                raise
    raise last  # every model was rate limited


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
