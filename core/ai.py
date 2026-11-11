"""Gemini access: one place for the model name, timeouts, pacing and retries."""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Callable, Optional

Waiter = Optional[Callable[[str], None]]


class AIError(Exception):
    """An AI failure with a message that is safe to show to the user."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _strip_fences(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return match.group(1) if match else text


def _retry_delay(error: Exception) -> Optional[float]:
    match = re.search(r"retry(?:Delay)?\W{0,4}(?:in\s+)?([0-9]+(?:\.[0-9]+)?)\s*s", str(error), re.I)
    return float(match.group(1)) if match else None


class GeminiClient:
    def __init__(self, api_key: str, model: str, timeout_s: int = 60, max_retries: int = 3,
                 rpm: int = 10, sleep: Callable[[float], None] = time.sleep):
        from google import genai

        self.model = model
        self.max_retries = max_retries
        self._sleep = sleep
        self._min_interval = 60.0 / rpm if rpm > 0 else 0.0
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._client = genai.Client(
            api_key=api_key,
            # v1beta carries the "-latest" model aliases; newer SDKs default to v1, which doesn't.
            http_options=genai.types.HttpOptions(api_version="v1beta", timeout=timeout_s * 1000),
        )

    def _pace(self, on_wait: Waiter) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._min_interval
        delay = slot - now
        if delay > 0:
            if delay > 2 and on_wait:
                on_wait(f"Pacing requests to stay within your Gemini limit ({int(delay)}s)")
            self._sleep(delay)

    def _call(self, system: str, prompt: str, schema: Optional[dict], on_wait: Waiter) -> str:
        from google.genai import errors, types
        import httpx

        config = types.GenerateContentConfig(system_instruction=system, temperature=0.2)
        if schema:
            config.response_mime_type = "application/json"
            config.response_json_schema = schema

        last_error: Optional[AIError] = None
        for attempt in range(self.max_retries + 1):
            self._pace(on_wait)
            wait = min(2.0 * (3 ** attempt), 30.0)
            try:
                response = self._client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                text = response.text
                if not text:
                    raise AIError("blocked", "Gemini returned no text for this request, possibly "
                                             "because of a safety filter. Try different content.")
                return text
            except AIError:
                raise
            except errors.APIError as exc:
                code = getattr(exc, "code", 0) or 0
                if code == 429:
                    if re.search(r"per ?day", str(exc), re.I):
                        raise AIError("quota", "Your Gemini daily quota is used up. Try again "
                                               "tomorrow or use a key with more quota.") from exc
                    wait = min(_retry_delay(exc) or 20.0, 65.0) + 1
                    last_error = AIError("rate_limit", "Gemini's rate limit was reached. Wait a "
                                                       "minute and try again.")
                elif code in (401, 403) or (code == 400 and "api key" in str(exc).lower()):
                    raise AIError("auth", "Gemini rejected the API key. Check GEMINI_API_KEY "
                                          "in your .env file.") from exc
                elif code == 404:
                    raise AIError("model", f"The Gemini model '{self.model}' isn't available to "
                                           "this key. Set GEMINI_MODEL in .env.") from exc
                elif code >= 500:
                    last_error = AIError("unavailable", "Gemini is temporarily unavailable. Try "
                                                        "again shortly.")
                else:
                    raise AIError("request", "Gemini could not process this request.") from exc
            except (httpx.TimeoutException, TimeoutError):
                last_error = AIError("timeout", "Gemini took too long to respond. Try again, or "
                                                "choose a faster model with GEMINI_MODEL.")
                wait = 2.0
            except httpx.HTTPError:
                last_error = AIError("network", "Couldn't reach Gemini. Check your internet "
                                                "connection.")
            if attempt < self.max_retries:
                if on_wait:
                    on_wait(f"{last_error.message.split('.')[0]}; retrying in {int(wait)}s")
                self._sleep(wait)
        raise last_error or AIError("unknown", "The AI request failed.")

    def generate_json(self, system: str, prompt: str, schema: dict, on_wait: Waiter = None) -> Any:
        text = self._call(system, prompt, schema, on_wait)
        try:
            return json.loads(_strip_fences(text))
        except json.JSONDecodeError:
            text = self._call(system, prompt, schema, on_wait)
            try:
                return json.loads(_strip_fences(text))
            except json.JSONDecodeError as exc:
                raise AIError("format", "Gemini returned an unreadable answer. Try again.") from exc


class UnconfiguredAI:
    """Stands in when no key is set, so the app still opens and can explain the fix."""

    model = "not configured"

    def generate_json(self, *args: Any, **kwargs: Any) -> Any:
        raise AIError("auth", "No Gemini API key is set. Add GEMINI_API_KEY to your .env file "
                              "and restart DocuMentor.")
