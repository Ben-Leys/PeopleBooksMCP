from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

import httpx

from peoplebooks_mcp.config import DEFAULT_REQUEST_TIMEOUT_SECONDS, DEFAULT_USER_AGENT

RETRYABLE_STATUS_CODES = {408, 429}


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    final_url: str
    text: str
    status_code: int
    elapsed_ms: int
    attempts: int
    content_hash: str
    source_metadata: dict[str, object]


class FetchError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        status_code: int | None = None,
        elapsed_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.status_code = status_code
        self.elapsed_ms = elapsed_ms


class PeopleBooksFetcher:
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        retries: int = 2,
        delay_seconds: float = 0.25,
        backoff_seconds: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._timeout_seconds = timeout_seconds
        self._retries = retries
        self._delay_seconds = delay_seconds
        self._backoff_seconds = backoff_seconds
        self._transport = transport

    def fetch(self, url: str) -> FetchResult:
        attempts_allowed = self._retries + 1
        started = time.perf_counter()
        last_error: str | None = None
        last_status: int | None = None

        with httpx.Client(
            headers={"User-Agent": self._user_agent},
            timeout=self._timeout_seconds,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            for attempt in range(1, attempts_allowed + 1):
                if self._delay_seconds:
                    time.sleep(self._delay_seconds)

                try:
                    response = client.get(url)
                except httpx.TimeoutException as error:
                    last_error = str(error)
                    if attempt == attempts_allowed:
                        break
                    self._sleep_before_retry(attempt)
                    continue
                except httpx.HTTPError as error:
                    last_error = str(error)
                    if attempt == attempts_allowed:
                        break
                    self._sleep_before_retry(attempt)
                    continue

                last_status = response.status_code
                if not _is_retryable_status(response.status_code):
                    if response.is_error:
                        elapsed_ms = _elapsed_ms(started)
                        raise FetchError(
                            f"HTTP {response.status_code} while fetching {url}",
                            attempts=attempt,
                            status_code=response.status_code,
                            elapsed_ms=elapsed_ms,
                        )
                    text = response.text
                    content_hash = sha256_content_hash(text)
                    return FetchResult(
                        url=url,
                        final_url=str(response.url),
                        text=text,
                        status_code=response.status_code,
                        elapsed_ms=_elapsed_ms(started),
                        attempts=attempt,
                        content_hash=content_hash,
                        source_metadata=_response_metadata(response),
                    )

                last_error = f"HTTP {response.status_code} while fetching {url}"
                if attempt != attempts_allowed:
                    self._sleep_before_retry(attempt, response=response)

        elapsed_ms = _elapsed_ms(started)
        raise FetchError(
            last_error or f"Failed to fetch {url}",
            attempts=attempts_allowed,
            status_code=last_status,
            elapsed_ms=elapsed_ms,
        )

    def _sleep_before_retry(self, attempt: int, *, response: httpx.Response | None = None) -> None:
        delay = _retry_after_seconds(response) if response is not None else None
        if delay is None:
            delay = self._backoff_seconds * attempt
        if delay:
            time.sleep(delay)


def sha256_content_hash(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _response_metadata(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "").split(";", 1)[0]
    metadata: dict[str, Any] = {
        "final_url": str(response.url),
    }
    if content_type:
        metadata["content_type"] = content_type
    return metadata


def _is_retryable_status(status_code: int) -> bool:
    return status_code >= 500 or status_code in RETRYABLE_STATUS_CODES


def _retry_after_seconds(response: httpx.Response | None) -> float | None:
    if response is None:
        return None
    retry_after = response.headers.get("retry-after")
    if retry_after is None:
        return None
    try:
        delay = float(retry_after)
    except ValueError:
        return None
    return max(0.0, delay)
