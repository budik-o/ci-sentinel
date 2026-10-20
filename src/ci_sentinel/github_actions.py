
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ci_sentinel.github_client import GitHubApiError, GitHubClient
from ci_sentinel.iso_datetime import parse_iso_datetime


@dataclass(frozen=True, slots=True)
class Repository:
    owner: str
    name: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", self.owner):
            raise ValueError("Invalid repository owner.")
        if self.owner.startswith("-") or self.owner.endswith("-"):
            raise ValueError("Invalid repository owner.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", self.name):
            raise ValueError("Invalid repository name.")
        if self.name in {".", ".."}:
            raise ValueError("Invalid repository name.")

    @classmethod
    def parse(cls, value: str) -> Repository:
        """Parse a repository in owner/repo format."""
        parts = value.split("/")
        if len(parts) != 2:
            raise ValueError("Repository must be in owner/repo format.")
        return cls(owner=parts[0], name=parts[1])

    def __str__(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    """Relevant details of a failed GitHub Actions workflow run."""

    run_id: int
    name: str
    branch: str | None
    created_at: datetime
    attempt: int
    url: str


def _parse_workflow_run(value: dict[str, Any]) -> WorkflowRun:
    """Convert a GitHub API workflow run into a WorkflowRun."""
    return WorkflowRun(
        run_id=value["id"],
        name=value.get("name") or "(unnamed workflow)",
        branch=value.get("head_branch"),
        created_at=parse_iso_datetime(value["created_at"]),
        attempt=value.get("run_attempt", 1),
        url=value["html_url"],
    )


def list_failed_workflow_runs(
    client: GitHubClient,
    repository: Repository,
    *,
    limit: int = 5,
) -> list[WorkflowRun]:
    """Fetch recent failed workflow runs from a GitHub repository."""
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    path = f"/repos/{repository.owner}/{repository.name}/actions/runs"

    with client.get(
        path,
        params={"status": "failure", "per_page": limit},
    ) as response:
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitHubApiError("GitHub returned invalid JSON for workflow runs.") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        raise GitHubApiError("GitHub response is missing the 'workflow_runs' list.")

    try:
        runs = [_parse_workflow_run(item) for item in payload["workflow_runs"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise GitHubApiError("Unexpected GitHub workflow run response format.") from exc

    return sorted(runs, key=lambda run: run.created_at, reverse=True)[:limit]