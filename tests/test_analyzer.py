"""Tests for diagnostic report validation and AI analysis."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from google.genai import errors
from pydantic import ValidationError

from ci_sentinel.analyzer import GEMINI_MODEL, DiagnosticReport, GeminiAnalysisError, analyze_log

VALID_REPORT = {
    "category": "lint",
    "root_cause": "Clippy found unused enum variants.",
    "suggested_fix": "Remove the unused variants or explicitly allow dead code.",
    "confidence_score": 0.95,
}


def test_valid_diagnostic_report() -> None:
    report = DiagnosticReport.model_validate(VALID_REPORT)

    assert report.category == "lint"
    assert report.model_dump() == VALID_REPORT


def test_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError):
        DiagnosticReport.model_validate({**VALID_REPORT, "category": "database"})


@pytest.mark.parametrize("score", [-0.1, 1.1])
def test_rejects_out_of_range_confidence(score: float) -> None:
    with pytest.raises(ValidationError):
        DiagnosticReport.model_validate({**VALID_REPORT, "confidence_score": score})


def test_requires_root_cause() -> None:
    report_without_cause = {key: value for key, value in VALID_REPORT.items() if key != "root_cause"}

    with pytest.raises(ValidationError):
        DiagnosticReport.model_validate(report_without_cause)


def test_analyze_log_returns_report() -> None:
    client = Mock()
    report = DiagnosticReport.model_validate(VALID_REPORT)
    client.models.generate_content.return_value.parsed = report

    result = analyze_log("error: unused enum variants", client=client)

    assert result == report
    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == GEMINI_MODEL
    assert "error: unused enum variants" in kwargs["contents"]
    assert kwargs["config"].response_schema is DiagnosticReport
    assert kwargs["config"].response_mime_type == "application/json"


def test_analyze_log_rejects_empty_log() -> None:
    client = Mock()

    with pytest.raises(ValueError, match="must not be empty"):
        analyze_log("  \n  ", client=client)

    client.models.generate_content.assert_not_called()


def test_analyze_log_handles_missing_report() -> None:
    client = Mock()
    client.models.generate_content.return_value.parsed = None

    with pytest.raises(GeminiAnalysisError, match="valid diagnostic report"):
        analyze_log("error: build failed", client=client)


def test_analyze_log_handles_api_error() -> None:
    client = Mock()
    client.models.generate_content.side_effect = errors.ClientError(
        429, {"message": "Quota exceeded"}
    )

    with pytest.raises(GeminiAnalysisError, match="HTTP 429"):
        analyze_log("error: build failed", client=client)