"""Command-line interface for CI Sentinel."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC

from ci_sentinel import __version__
from ci_sentinel.github_actions import (
    Repository,
    download_job_logs,
    list_failed_jobs,
    list_failed_workflow_runs,
    truncate_log,
)
from ci_sentinel.github_client import GitHubApiError, GitHubClient


def _repository_arg(value: str) -> Repository:
    """Convert command-line repository input into a validated identifier."""
    try:
        return Repository.parse(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _limit_arg(value: str) -> int:
    """Validate the one-page GitHub API result limit."""
    try:
        limit = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Limit must be an integer between 1 and 100.") from exc
    if not 1 <= limit <= 100:
        raise argparse.ArgumentTypeError("Limit must be between 1 and 100.")
    return limit


def _positive_int_arg(value: str) -> int:
    """Validate an ID or run attempt number."""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected a positive integer.") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("Expected a positive integer.")
    return number


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and return a conventional process exit code."""
    parser = argparse.ArgumentParser(
        prog="ci-sentinel",
        description="Analyze failed GitHub Actions jobs and expose diagnostics metrics.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    commands = parser.add_subparsers(dest="command")
    failures = commands.add_parser("list-failures", help="List recent failed workflow runs.")
    failures.add_argument("repository", type=_repository_arg, metavar="owner/repo")
    failures.add_argument(
        "--limit", type=_limit_arg, default=5, metavar="N", help="Number of runs (1-100)."
    )

    inspect = commands.add_parser("inspect-run", help="Inspect failed jobs in a workflow run.")
    inspect.add_argument("repository", type=_repository_arg, metavar="owner/repo")
    inspect.add_argument("run_id", type=_positive_int_arg, metavar="RUN_ID")
    inspect.add_argument(
        "--attempt", type=_positive_int_arg, metavar="N", help="Inspect a specific run attempt."
    )
    inspect.add_argument("--logs", action="store_true", help="Print full logs for failed jobs.")

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    if args.command is None:
        parser.print_help()
        return 2

    try:
        with GitHubClient() as client:
            if args.command == "inspect-run":
                jobs = list_failed_jobs(client, args.repository, args.run_id, attempt=args.attempt)
                if not jobs:
                    print(f"No failed jobs found for run {args.run_id} in {args.repository}.")
                    return 0
                for job in jobs:
                    print(f"- {job.name} (job {job.job_id}, {job.conclusion})")
                    print(f"  URL: {job.url}")
                    if args.logs:
                        print(f"  Logs for job {job.job_id}:")
                        print(truncate_log(download_job_logs(client, args.repository, job.job_id)))
                return 0

            runs = list_failed_workflow_runs(client, args.repository, limit=args.limit)
    except GitHubApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not runs:
        print(f"No failed workflow runs found for {args.repository}.")
        return 0

    print(f"Recent failed workflow runs for {args.repository}:")
    for run in runs:
        created = run.created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        print(f"- {run.name} (run {run.run_id}, attempt {run.attempt})")
        print(f"  Branch: {run.branch or '(unknown)'} | Created: {created}")
        print(f"  URL: {run.url}")
    return 0
