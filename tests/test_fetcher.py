from __future__ import annotations

import httpx
import pytest

from peoplebooks_mcp.scraper.fetcher import FetchError, PeopleBooksFetcher, sha256_content_hash


def test_fetcher_retries_server_errors_and_hashes_success() -> None:
    responses = [
        httpx.Response(503, text="busy"),
        httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    fetcher = PeopleBooksFetcher(
        user_agent="PeopleBooksMCP test",
        transport=httpx.MockTransport(handler),
        delay_seconds=0,
        backoff_seconds=0,
    )

    result = fetcher.fetch("https://docs.oracle.com/example.html")

    assert result.text == "<html>ok</html>"
    assert result.status_code == 200
    assert result.attempts == 2
    assert result.content_hash == sha256_content_hash("<html>ok</html>")
    assert result.source_metadata["content_type"] == "text/html"


def test_fetcher_records_timeout_as_fetch_error_after_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    fetcher = PeopleBooksFetcher(
        transport=httpx.MockTransport(handler),
        delay_seconds=0,
        backoff_seconds=0,
        retries=1,
    )

    with pytest.raises(FetchError) as error:
        fetcher.fetch("https://docs.oracle.com/example.html")

    assert "timed out" in str(error.value)
    assert error.value.attempts == 2
    assert error.value.status_code is None


def test_fetcher_retries_rate_limit_responses() -> None:
    responses = [
        httpx.Response(429, text="rate limited"),
        httpx.Response(200, text="<html>ok</html>"),
    ]

    fetcher = PeopleBooksFetcher(
        transport=httpx.MockTransport(lambda request: responses.pop(0)),
        delay_seconds=0,
        backoff_seconds=0,
    )

    result = fetcher.fetch("https://docs.oracle.com/example.html")

    assert result.status_code == 200
    assert result.attempts == 2


def test_fetcher_reports_exhausted_rate_limit_retries() -> None:
    fetcher = PeopleBooksFetcher(
        transport=httpx.MockTransport(lambda request: httpx.Response(429, text="rate limited")),
        delay_seconds=0,
        backoff_seconds=0,
        retries=1,
    )

    with pytest.raises(FetchError) as error:
        fetcher.fetch("https://docs.oracle.com/example.html")

    assert "HTTP 429" in str(error.value)
    assert error.value.attempts == 2
    assert error.value.status_code == 429
