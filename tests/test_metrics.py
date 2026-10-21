"""Tests for Prometheus metrics recorded by CI analysis."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY, generate_latest

from ci_sentinel.analyzer import DiagnosticReport, GeminiAnalysisError
from ci_sentinel.cli import main
from ci_sentinel.github_actions import WorkflowJob, WorkflowRun


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _run() -> WorkflowRun:
    return WorkflowRun(123, "CI", "main", datetime(2026, 10, 20, tzinfo=UTC), 1, "url")


def _job(job_id: int) -> WorkflowJob:
    return WorkflowJob(job_id, "test", "failure", "url")


def test_successful_analysis_records_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    report = DiagnosticReport(
        category="lint", root_cause="Formatting failed", suggested_fix="Run cargo fmt",
        confidence_score=0.9,
    )
    before_success = _sample("ci_sentinel_analyses_total", {"category": "lint"})
    before_gemini = _sample("ci_sentinel_gemini_request_duration_seconds_count")
    before_processing = _sample("ci_sentinel_job_processing_duration_seconds_count")

    with (
        patch("ci_sentinel.cli.GitHubClient"),
        patch("ci_sentinel.cli.genai.Client"),
        patch("ci_sentinel.cli.list_failed_workflow_runs", return_value=[_run()]),
        patch("ci_sentinel.cli.list_failed_jobs", return_value=[_job(11)]),
        patch("ci_sentinel.cli.download_job_logs", return_value="cargo fmt failed"),
        patch("ci_sentinel.cli.analyze_log", return_value=report),
    ):
        assert main(["analyze", "owner/repo"]) == 0

    assert _sample("ci_sentinel_analyses_total", {"category": "lint"}) == before_success + 1
    assert _sample("ci_sentinel_gemini_request_duration_seconds_count") == before_gemini + 1
    assert _sample("ci_sentinel_job_processing_duration_seconds_count") == before_processing + 1


def test_gemini_failure_is_counted_and_next_job_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    report = DiagnosticReport(
        category="test", root_cause="Assertion failed", suggested_fix="Fix assertion",
        confidence_score=0.8,
    )
    before_error = _sample("ci_sentinel_api_errors_total", {"service": "gemini"})
    before_success = _sample("ci_sentinel_analyses_total", {"category": "test"})
    before_gemini = _sample("ci_sentinel_gemini_request_duration_seconds_count")

    with (
        patch("ci_sentinel.cli.GitHubClient"),
        patch("ci_sentinel.cli.genai.Client"),
        patch("ci_sentinel.cli.list_failed_workflow_runs", return_value=[_run()]),
        patch("ci_sentinel.cli.list_failed_jobs", return_value=[_job(11), _job(12)]),
        patch("ci_sentinel.cli.download_job_logs", return_value="tests failed"),
        patch("ci_sentinel.cli.analyze_log", side_effect=[GeminiAnalysisError("HTTP 503"), report]),
    ):
        assert main(["analyze", "owner/repo"]) == 1

    assert _sample("ci_sentinel_api_errors_total", {"service": "gemini"}) == before_error + 1
    assert _sample("ci_sentinel_analyses_total", {"category": "test"}) == before_success + 1
    assert _sample("ci_sentinel_gemini_request_duration_seconds_count") == before_gemini + 2


def test_github_api_error_is_counted() -> None:
    from ci_sentinel.github_client import GitHubApiError

    before = _sample("ci_sentinel_api_errors_total", {"service": "github"})
    with (
        patch("ci_sentinel.cli.GitHubClient"),
        patch("ci_sentinel.cli.list_failed_workflow_runs", side_effect=GitHubApiError("403")),
    ):
        assert main(["list-failures", "owner/repo"]) == 1
    assert _sample("ci_sentinel_api_errors_total", {"service": "github"}) == before + 1


def test_metrics_have_prometheus_text_format() -> None:
    output = generate_latest(REGISTRY).decode("utf-8")
    assert "ci_sentinel_analyses_total" in output
    assert "ci_sentinel_api_errors_total" in output
    assert "ci_sentinel_gemini_request_duration_seconds_bucket" in output
    assert "ci_sentinel_job_processing_duration_seconds_count" in output
