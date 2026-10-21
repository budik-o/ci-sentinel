"""Tests for GitHub Actions utilities and the shared GitHub API helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
import requests

from ci_sentinel import github_client
from ci_sentinel.github_actions import Repository, list_failed_workflow_runs, truncate_log
from ci_sentinel.github_client import (
    API_ROOT,
    GitHubApiError,
    GitHubClient,
    GitHubTransportError,
    auth_headers,
    raise_for_error_response,
)
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
        2026, 10, 20, 12, 30, tzinfo=UTC
    )


def test_parse_offset_timestamp() -> None:
    assert parse_iso_datetime("2026-10-20T14:30:00+02:00").astimezone(UTC) == (
        datetime(2026, 10, 20, 12, 30, tzinfo=UTC)
    )


@pytest.mark.parametrize("value", ["not-a-date", "2026-10-20T12:30:00"])
def test_reject_invalid_or_naive_timestamp(value: str) -> None:
    with pytest.raises(ValueError):
        parse_iso_datetime(value)


def test_client_get_passes_headers_params_and_timeout() -> None:
    session = Mock(spec=requests.Session)
    response = make_response(200, '{"ok": true}')
    session.get.return_value = response

    client = GitHubClient(token="test-token", session=session)
    result = client.get("/repos/octocat/Hello-World", params={"per_page": 10})

    assert result is response
    session.get.assert_called_once_with(
        f"{API_ROOT}/repos/octocat/Hello-World",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "ci-sentinel",
            "Authorization": "Bearer test-token",
        },
        params={"per_page": 10},
        timeout=(5.0, 30.0),
        stream=False,
    )


def test_client_supports_streaming_and_custom_timeout() -> None:
    session = Mock(spec=requests.Session)
    session.get.return_value = make_response(200, "log text")
    client = GitHubClient(session=session, timeout=(2.0, 15.0))

    client.get("/repos/example/repo/actions/jobs/123/logs", stream=True)

    assert session.get.call_args.kwargs["stream"] is True
    assert session.get.call_args.kwargs["timeout"] == (2.0, 15.0)


@pytest.mark.parametrize(
    "path", ["repos/owner/repo", "//evil.example/path", "https://evil.example"]
)
def test_client_rejects_non_api_paths(path: str) -> None:
    session = Mock(spec=requests.Session)
    with pytest.raises(ValueError, match="must start"):
        GitHubClient(session=session).get(path)
    session.get.assert_not_called()


@pytest.mark.parametrize("timeout_error", [requests.ConnectTimeout, requests.ReadTimeout])
def test_client_converts_timeouts(timeout_error: type[requests.Timeout]) -> None:
    session = Mock(spec=requests.Session)
    session.get.side_effect = timeout_error("timed out")

    with pytest.raises(GitHubTransportError, match="timed out") as exc_info:
        GitHubClient(session=session).get("/rate_limit")
    assert exc_info.value.status_code is None
    assert isinstance(exc_info.value.__cause__, requests.Timeout)


def test_client_converts_connection_error() -> None:
    session = Mock(spec=requests.Session)
    session.get.side_effect = requests.ConnectionError("connection refused")

    with pytest.raises(GitHubTransportError, match="connection refused"):
        GitHubClient(session=session).get("/rate_limit")


def test_client_closes_failed_http_responses() -> None:
    response = make_response(404)
    response.close = Mock()
    session = Mock(spec=requests.Session)
    session.get.return_value = response

    with pytest.raises(GitHubApiError) as exc_info:
        GitHubClient(session=session).get("/repos/missing/missing")
    assert exc_info.value.status_code == 404
    response.close.assert_called_once_with()


def test_client_does_not_close_injected_session() -> None:
    session = Mock(spec=requests.Session)
    with GitHubClient(session=session):
        pass
    session.close.assert_not_called()


def test_client_closes_owned_session(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Mock(spec=requests.Session)
    monkeypatch.setattr(github_client.requests, "Session", Mock(return_value=session))
    with github_client.GitHubClient():
        pass
    session.close.assert_called_once_with()


@pytest.mark.parametrize("timeout", [(0.0, 5.0), (5.0, -1.0)])
def test_client_rejects_invalid_timeout(timeout: tuple[float, float]) -> None:
    with pytest.raises(ValueError, match="positive"):
        GitHubClient(timeout=timeout)


def sample_run(run_id: int = 123) -> dict[str, object]:
    return {
        "id": run_id,
        "name": "CI",
        "head_branch": "main",
        "created_at": "2026-10-20T12:00:00Z",
        "run_attempt": 1,
        "html_url": f"https://github.com/owner/repo/actions/runs/{run_id}",
    }


def mock_runs_client(payload: object) -> tuple[GitHubClient, Mock]:
    session = Mock(spec=requests.Session)
    session.get.return_value = make_response(200, json.dumps(payload))
    return GitHubClient(session=session), session


def test_list_failed_runs_fetches_and_parses_results() -> None:
    client, session = mock_runs_client({"workflow_runs": [sample_run()]})

    runs = list_failed_workflow_runs(client, Repository.parse("owner/repo"), limit=5)

    assert len(runs) == 1
    assert runs[0].run_id == 123
    assert runs[0].name == "CI"
    assert runs[0].branch == "main"
    assert runs[0].created_at == datetime(2026, 10, 20, 12, tzinfo=UTC)
    assert session.get.call_args.args == (f"{API_ROOT}/repos/owner/repo/actions/runs",)
    assert session.get.call_args.kwargs["params"] == {"status": "failure", "per_page": 5}


def test_list_failed_runs_handles_empty_results() -> None:
    client, _ = mock_runs_client({"workflow_runs": []})
    assert list_failed_workflow_runs(client, Repository.parse("owner/repo")) == []


def test_list_failed_runs_rejects_bad_response() -> None:
    client, _ = mock_runs_client({"unexpected": []})
    with pytest.raises(GitHubApiError, match="workflow_runs"):
        list_failed_workflow_runs(client, Repository.parse("owner/repo"))


def test_list_failed_runs_propagates_http_errors() -> None:
    session = Mock(spec=requests.Session)
    session.get.return_value = make_response(403)
    with pytest.raises(GitHubApiError, match="forbidden"):
        list_failed_workflow_runs(GitHubClient(session=session), Repository.parse("owner/repo"))


def test_list_failed_jobs_filters_results() -> None:
    from ci_sentinel.github_actions import list_failed_jobs

    jobs = [
        {"id": 10, "name": "build", "conclusion": "success", "html_url": "https://example/10"},
        {"id": 11, "name": "test", "conclusion": "failure", "html_url": "https://example/11"},
        {"id": 12, "name": "lint", "conclusion": "timed_out", "html_url": "https://example/12"},
    ]
    session = Mock(spec=requests.Session)
    session.get.return_value = make_response(200, json.dumps({"jobs": jobs}))

    result = list_failed_jobs(GitHubClient(session=session), Repository.parse("owner/repo"), 123)

    assert [job.job_id for job in result] == [11, 12]
    assert session.get.call_args.args[0] == f"{API_ROOT}/repos/owner/repo/actions/runs/123/jobs"
    assert session.get.call_args.kwargs["params"] == {"per_page": 100}


def test_list_failed_jobs_supports_run_attempt() -> None:
    from ci_sentinel.github_actions import list_failed_jobs

    session = Mock(spec=requests.Session)
    session.get.return_value = make_response(200, '{"jobs": []}')
    assert list_failed_jobs(
        GitHubClient(session=session), Repository.parse("owner/repo"), 123, attempt=2
    ) == []
    assert session.get.call_args.args[0].endswith("/runs/123/attempts/2/jobs")


def test_list_failed_jobs_rejects_invalid_response() -> None:
    from ci_sentinel.github_actions import list_failed_jobs

    session = Mock(spec=requests.Session)
    session.get.return_value = make_response(200, '{}')
    with pytest.raises(GitHubApiError, match="jobs"):
        list_failed_jobs(GitHubClient(session=session), Repository.parse("owner/repo"), 123)


def test_download_job_logs_returns_plain_text() -> None:
    from ci_sentinel.github_actions import download_job_logs

    session = Mock(spec=requests.Session)
    session.get.return_value = make_response(200, "Error: tests failed\n")
    result = download_job_logs(GitHubClient(session=session), Repository.parse("owner/repo"), 11)

    assert result == "Error: tests failed\n"
    assert session.get.call_args.args[0].endswith("/actions/jobs/11/logs")


def test_truncate_log_keeps_short_logs_unchanged() -> None:
    log = "error: compilation failed\n"
    assert truncate_log(log) == log


def test_truncate_log_preserves_end_and_respects_limit() -> None:
    log = "setup output\n" * 2_000 + "error: compilation failed\n"
    result = truncate_log(log)

    assert len(result) == 12_000
    assert result.startswith("[... earlier log output omitted ...]")
    assert result.endswith("error: compilation failed\n")
