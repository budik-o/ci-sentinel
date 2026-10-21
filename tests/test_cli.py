"""Tests for CLI commands, argument parsing, and error handling."""

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


def test_inspect_run_truncates_long_logs(capsys: pytest.CaptureFixture[str]) -> None:
    from ci_sentinel.github_actions import WorkflowJob

    job = WorkflowJob(11, "test", "failure", "https://github.com/owner/repo/actions/jobs/11")
    raw_log = "setup line\n" * 2_000 + "error: tests failed\n"

    with patch("ci_sentinel.cli.GitHubClient"):
        with patch("ci_sentinel.cli.list_failed_jobs", return_value=[job]):
            with patch("ci_sentinel.cli.download_job_logs", return_value=raw_log):
                assert main(["inspect-run", "owner/repo", "123", "--logs"]) == 0

    output = capsys.readouterr().out
    assert "earlier log output omitted" in output
    assert "error: tests failed" in output
    assert raw_log not in output


def test_analyze_runs_diagnostics_with_truncated_logs(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from ci_sentinel.analyzer import DiagnosticReport
    from ci_sentinel.github_actions import WorkflowJob

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    run = WorkflowRun(
        123, "CI", "main", datetime(2026, 10, 20, tzinfo=UTC), 2,
        "https://github.com/owner/repo/actions/runs/123",
    )
    job = WorkflowJob(11, "test", "failure", "https://github.com/owner/repo/actions/jobs/11")
    report = DiagnosticReport(
        category="test", root_cause="Assertion failed", suggested_fix="Fix assertion",
        confidence_score=0.9,
    )
    long_log = "setup output\n" * 2000 + "error: assertion failed"

    with (
        patch("ci_sentinel.cli.GitHubClient"),
        patch("ci_sentinel.cli.genai.Client"),
        patch("ci_sentinel.cli.list_failed_workflow_runs", return_value=[run]) as get_runs,
        patch("ci_sentinel.cli.list_failed_jobs", return_value=[job]) as get_jobs,
        patch("ci_sentinel.cli.download_job_logs", return_value=long_log),
        patch("ci_sentinel.cli.analyze_log", return_value=report) as analyze,
    ):
        assert main(["analyze", "owner/repo"]) == 0

    output = capsys.readouterr().out
    assert "Run 123" in output
    assert '"category": "test"' in output
    assert get_runs.call_args.kwargs["limit"] == 1
    assert get_jobs.call_args.kwargs["attempt"] == 2
    assert len(analyze.call_args.args[0]) == 12_000
    assert analyze.call_args.args[0].endswith("error: assertion failed")


def test_analyze_handles_empty_runs(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with (
        patch("ci_sentinel.cli.GitHubClient"),
        patch("ci_sentinel.cli.genai.Client") as gemini,
        patch("ci_sentinel.cli.list_failed_workflow_runs", return_value=[]),
    ):
        assert main(["analyze", "owner/repo"]) == 0
    assert "No failed workflow runs" in capsys.readouterr().out
    gemini.assert_not_called()


def test_analyze_handles_empty_jobs(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    run = WorkflowRun(
        123, "CI", "main", datetime(2026, 10, 20, tzinfo=UTC), 1,
        "https://github.com/owner/repo/actions/runs/123",
    )
    with (
        patch("ci_sentinel.cli.GitHubClient"),
        patch("ci_sentinel.cli.genai.Client"),
        patch("ci_sentinel.cli.list_failed_workflow_runs", return_value=[run]),
        patch("ci_sentinel.cli.list_failed_jobs", return_value=[]),
        patch("ci_sentinel.cli.analyze_log") as analyze,
    ):
        assert main(["analyze", "owner/repo"]) == 0
    assert "No failed jobs with logs" in capsys.readouterr().out
    analyze.assert_not_called()


def test_analyze_rejects_missing_key(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with patch("ci_sentinel.cli.GitHubClient") as github:
        assert main(["analyze", "owner/repo"]) == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().err
    github.assert_not_called()


def test_analyze_reports_gemini_errors(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from ci_sentinel.analyzer import GeminiAnalysisError
    from ci_sentinel.github_actions import WorkflowJob

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    run = WorkflowRun(
        123, "CI", "main", datetime(2026, 10, 20, tzinfo=UTC), 1,
        "https://github.com/owner/repo/actions/runs/123",
    )
    job = WorkflowJob(11, "test", "failure", "https://github.com/owner/repo/actions/jobs/11")
    with (
        patch("ci_sentinel.cli.GitHubClient"),
        patch("ci_sentinel.cli.genai.Client"),
        patch("ci_sentinel.cli.list_failed_workflow_runs", return_value=[run]),
        patch("ci_sentinel.cli.list_failed_jobs", return_value=[job]),
        patch("ci_sentinel.cli.download_job_logs", return_value="error: build failed"),
        patch("ci_sentinel.cli.analyze_log", side_effect=GeminiAnalysisError("HTTP 503")),
    ):
        assert main(["analyze", "owner/repo"]) == 1
    assert "HTTP 503" in capsys.readouterr().err


def test_analyze_rejects_excessive_limit() -> None:
    assert main(["analyze", "owner/repo", "--limit", "6"]) == 2