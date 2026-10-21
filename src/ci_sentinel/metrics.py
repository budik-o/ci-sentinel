"""Prometheus metrics for CI Sentinel analysis."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

ANALYSES_TOTAL = Counter(
    "ci_sentinel_analyses_total",
    "Successfully analyzed CI jobs, by diagnostic category.",
    ["category"],
)

API_ERRORS_TOTAL = Counter(
    "ci_sentinel_api_errors_total",
    "Failed GitHub or Gemini API operations.",
    ["service"],
)

JOB_PROCESSING_DURATION = Histogram(
    "ci_sentinel_job_processing_duration_seconds",
    "Time spent downloading and analyzing one failed job.",
    buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)

GEMINI_REQUEST_DURATION = Histogram(
    "ci_sentinel_gemini_request_duration_seconds",
    "Time spent on one Gemini analysis request, including SDK retries.",
    buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)

# Initialize the known low-cardinality label values, including zero counts.
for category in (
    "build", "test", "lint", "dependency", "configuration", "infrastructure", "unknown"
):
    ANALYSES_TOTAL.labels(category=category)

for service in ("github", "gemini"):
    API_ERRORS_TOTAL.labels(service=service)
