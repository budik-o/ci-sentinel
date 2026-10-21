from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from ci_sentinel.cli import main
from ci_sentinel.github_actions import WorkflowRun
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
        created_at=datetime(2026, 10, 20, 12, tzinfo=UTC),
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
        with patch(
            "ci_sentinel.cli.list_failed_workflow_runs", side_effect=GitHubApiError("Forbidden")
        ):
            assert main(["list-failures", "owner/repo"]) == 1
    assert "Forbidden" in capsys.readouterr().err


def test_inspect_run_lists_only_failed_jobs(capsys: pytest.CaptureFixture[str]) -> None:
    from ci_sentinel.github_actions import WorkflowJob

    job = WorkflowJob(11, "test", "failure", "https://github.com/owner/repo/actions/jobs/11")
    with patch("ci_sentinel.cli.GitHubClient"):
        with patch("ci_sentinel.cli.list_failed_jobs", return_value=[job]) as fetch:
            assert main(["inspect-run", "owner/repo", "123", "--attempt", "2"]) == 0
    assert "test (job 11, failure)" in capsys.readouterr().out
    assert fetch.call_args.kwargs["attempt"] == 2


def test_inspect_run_optionally_downloads_logs(capsys: pytest.CaptureFixture[str]) -> None:
    from ci_sentinel.github_actions import WorkflowJob

    job = WorkflowJob(11, "test", "failure", "https://github.com/owner/repo/actions/jobs/11")
    with patch("ci_sentinel.cli.GitHubClient"):
        with patch("ci_sentinel.cli.list_failed_jobs", return_value=[job]):
            with patch("ci_sentinel.cli.download_job_logs", return_value="Tests failed") as logs:
                assert main(["inspect-run", "owner/repo", "123", "--logs"]) == 0
                logs.assert_called_once()
    assert "Tests failed" in capsys.readouterr().out


def test_inspect_run_rejects_invalid_run_id() -> None:
    assert main(["inspect-run", "owner/repo", "0"]) == 2


def test_inspect_run_reports_api_error(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("ci_sentinel.cli.GitHubClient"):
        with patch("ci_sentinel.cli.list_failed_jobs", side_effect=GitHubApiError("Forbidden")):
            assert main(["inspect-run", "owner/repo", "123"]) == 1
    assert "Forbidden" in capsys.readouterr().err
