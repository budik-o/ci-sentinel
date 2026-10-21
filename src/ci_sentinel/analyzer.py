"""Structured CI failure diagnostics and AI-powered log analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DiagnosticReport(BaseModel):
    """Structured diagnosis of a failed CI job."""

    category: Literal[
        "build", "test", "lint", "dependency", "configuration", "infrastructure", "unknown"
    ] = Field(description="Most likely category of the failure.")
    root_cause: str = Field(min_length=1, description="Concise explanation of the likely cause.")
    suggested_fix: str = Field(min_length=1, description="Actionable suggestion to fix the failure.")
    confidence_score: float = Field(
        ge=0.0, le=1.0, description="Confidence in the diagnosis, from 0.0 to 1.0."
    )
