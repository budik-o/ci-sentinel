"""Tests for diagnostic report validation and AI analysis."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ci_sentinel.analyzer import DiagnosticReport

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
