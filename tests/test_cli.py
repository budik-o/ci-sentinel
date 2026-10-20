from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from ci_sentinel.cli import main
from ci_sentinel.github_actions import Repository, WorkflowRun
from ci_sentinel.github_client import GitHubApiError


def test_version_exits_successfully() -> None:
    assert main(["--version"]) == 0


def test_no_arguments_returns_usage_error() -> None:
    assert main([]) == 2


def test_unknown_option_returns_usage_error() -> None:
    assert main(["--unknown"]) == 2


def test_help_exits_successfully() -> None:
    assert main(["--help"]) == 0


def test_list_failures_prints_runs(capsys: pytest.CaptureFixture[str]) -> None:
    run = WorkflowRun(
        run_id=123,
        name="CI",
        branch="main",
        created_at=datetime(2026, 10, 20, 12, tzinfo=timezone.utc),
        attempt=1,
        url="https://github.com/owner/repo/actions/runs/123",
    )
    with patch("ci_sentinel.cli.GitHubClient"):
        with patch("ci_sentinel.cli.list_failed_workflow_runs", return_value=[run]):
            assert main(["list-failures", "owner/repo", "--limit", "5"]) == 0

    output = capsys.readouterr().out
    assert "CI (run 123, attempt 1)" in output
    assert run.url in output


def test_list_failures_handles_empty_results(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("ci_sentinel.cli.GitHubClient"):
        with patch("ci_sentinel.cli.list_failed_workflow_runs", return_value=[]):
            assert main(["list-failures", "owner/repo"]) == 0
    assert "No failed workflow runs" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args", [["list-failures", "bad-repo"], ["list-failures", "owner/repo", "--limit", "0"]]
)
def test_list_failures_rejects_invalid_arguments(args: list[str]) -> None:
    with patch("ci_sentinel.cli.GitHubClient") as client:
        assert main(args) == 2
    client.assert_not_called()


def test_list_failures_reports_api_error(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("ci_sentinel.cli.GitHubClient"):
        with patch("ci_sentinel.cli.list_failed_workflow_runs", side_effect=GitHubApiError("Forbidden")):
            assert main(["list-failures", "owner/repo"]) == 1
    assert "Forbidden" in capsys.readouterr().err
