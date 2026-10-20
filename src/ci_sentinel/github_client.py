"""GitHub REST API constants, auth headers, and error translation."""

from __future__ import annotations

import os

import requests

API_ROOT = "https://api.github.com"
API_VERSION = "2026-03-10"


class GitHubApiError(RuntimeError):
    """Raised when GitHub returns an unsuccessful HTTP response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def auth_headers(token: str | None = None) -> dict[str, str]:
    """Build GitHub REST headers, using GITHUB_TOKEN as a fallback."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
    }
    actual_token = token if token is not None else os.environ.get("GITHUB_TOKEN")
    if actual_token:
        headers["Authorization"] = f"Bearer {actual_token}"
    return headers


def raise_for_error_response(response: requests.Response) -> None:
    """Translate GitHub HTTP error statuses into readable exceptions."""
    status = response.status_code
    if status < 400:
        return

    if status == 401:
        message = "GitHub authentication failed (401): check GITHUB_TOKEN."
    elif status == 404:
        message = "GitHub resource not found (404): check its name, ID, and access permissions."
    elif status == 429 or (
        status == 403
        and (
            response.headers.get("X-RateLimit-Remaining") == "0"
            or "rate limit" in response.text.lower()
        )
    ):
        message = "GitHub API rate limit reached: retry after the applicable cooldown."
    elif status == 403:
        message = "GitHub request forbidden (403): check token permissions or access policy."
    elif status == 410:
        message = "GitHub resource is no longer available (410)."
    elif status == 422:
        message = "GitHub rejected the request parameters (422)."
    elif status >= 500:
        message = f"GitHub server error ({status}): retry later."
    else:
        # Cap untrusted error details to avoid filling CLI output.
        snippet = response.text[:200].replace("\n", " ")
        message = f"GitHub API request failed ({status}): {snippet}"

    raise GitHubApiError(message, status_code=status)
