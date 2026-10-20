"""Tests for GitHub Actions utilities and the shared GitHub API helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import requests

from ci_sentinel.github_actions import Repository
from ci_sentinel.github_client import GitHubApiError, auth_headers, raise_for_error_response
from ci_sentinel.iso_datetime import parse_iso_datetime


def test_parse_valid_repository() -> None:
    repository = Repository.parse("open-source/.github")
    assert repository.owner == "open-source"
    assert repository.name == ".github"
    assert str(repository) == "open-source/.github"


@pytest.mark.parametrize(
    "value",
    ["", "owner", "owner/repo/extra", "/repo", "owner/", "a b/repo", "owner/..", "-x/repo"],
)
def test_reject_invalid_repository(value: str) -> None:
    with pytest.raises(ValueError):
        Repository.parse(value)


def test_direct_construction_cannot_bypass_validation() -> None:
    with pytest.raises(ValueError):
        Repository(owner="", name="repo")


def make_response(status: int, body: str = "") -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = body.encode("utf-8")
    return response


def test_auth_headers_accept_injected_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ignored")
    headers = auth_headers("injected")
    assert headers["Authorization"] == "Bearer injected"
    assert headers["X-GitHub-Api-Version"] == "2026-03-10"


def test_auth_headers_omit_authorization_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert "Authorization" not in auth_headers()


@pytest.mark.parametrize("status", [200, 204, 302])
def test_no_error_for_non_error_http_status(status: int) -> None:
    raise_for_error_response(make_response(status))


@pytest.mark.parametrize(
    ("status", "expected_message"),
    [
        (401, "authentication"),
        (403, "forbidden"),
        (404, "not found"),
        (410, "no longer available"),
        (422, "parameters"),
        (429, "rate limit"),
        (503, "server error"),
    ],
)
def test_error_translation(status: int, expected_message: str) -> None:
    with pytest.raises(GitHubApiError, match=expected_message) as exc_info:
        raise_for_error_response(make_response(status))
    assert exc_info.value.status_code == status


def test_rate_limited_403_has_distinct_message() -> None:
    response = make_response(403)
    response.headers["X-RateLimit-Remaining"] = "0"
    with pytest.raises(GitHubApiError, match="rate limit"):
        raise_for_error_response(response)


def test_parse_github_utc_timestamp() -> None:
    assert parse_iso_datetime("2026-10-20T12:30:00Z") == datetime(
        2026, 10, 20, 12, 30, tzinfo=timezone.utc
    )


def test_parse_offset_timestamp() -> None:
    assert parse_iso_datetime("2026-10-20T14:30:00+02:00").astimezone(timezone.utc) == (
        datetime(2026, 10, 20, 12, 30, tzinfo=timezone.utc)
    )


@pytest.mark.parametrize("value", ["not-a-date", "2026-10-20T12:30:00"])
def test_reject_invalid_or_naive_timestamp(value: str) -> None:
    with pytest.raises(ValueError):
        parse_iso_datetime(value)
