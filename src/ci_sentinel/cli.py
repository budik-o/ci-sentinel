"""Command-line interface for CI Sentinel."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC

from google import genai
from prometheus_client import start_http_server

from ci_sentinel import __version__
from ci_sentinel.analyzer import GeminiAnalysisError, analyze_log
from ci_sentinel.github_actions import (
    Repository,
    WorkflowRun,
    download_job_logs,
    list_failed_jobs,
    list_failed_workflow_runs,
    truncate_log,
)
from ci_sentinel.github_client import GitHubApiError, GitHubClient
from ci_sentinel.metrics import (
    ANALYSES_TOTAL,
    API_ERRORS_TOTAL,
    GEMINI_REQUEST_DURATION,
    JOB_PROCESSING_DURATION,
)


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


def _analyze_runs(
    github: GitHubClient,
    gemini: genai.Client,
    repository: Repository,
    runs: list[WorkflowRun],
    *,
    processed: set[tuple[int, int, int]] | None = None,
) -> tuple[int, int]:
    """Analyze failed jobs, optionally skipping previously processed attempts."""

    analyzed = 0
    failed = 0
    for run in runs:
        jobs = list_failed_jobs(github, repository, run.run_id, attempt=run.attempt)
        for job in jobs:
            key = (run.run_id, run.attempt, job.job_id)
            if processed is not None and key in processed:
                continue

            with JOB_PROCESSING_DURATION.time():
                log = truncate_log(download_job_logs(github, repository, job.job_id))
                if not log.strip():
                    if processed is not None:
                        processed.add(key)
                    continue

                try:
                    with GEMINI_REQUEST_DURATION.time():
                        report = analyze_log(log, client=gemini)
                except GeminiAnalysisError as exc:
                    API_ERRORS_TOTAL.labels(service="gemini").inc()
                    print(f"Gemini analysis failed for job {job.job_id}: {exc}", file=sys.stderr)
                    failed += 1
                    continue

                ANALYSES_TOTAL.labels(category=report.category).inc()
                print(f"Run {run.run_id} | {job.name} (job {job.job_id})", flush=True)
                print(report.model_dump_json(indent=2), flush=True)
                analyzed += 1
                if processed is not None:
                    processed.add(key)

    if analyzed or failed:
        print(f"\nAnalysis complete: {analyzed} successful, {failed} failed.", flush=True)
    elif processed is None:
        print(f"No failed jobs with logs found for {repository}.")
    return analyzed, failed


def _serve(
    repository: Repository,
    *,
    limit: int,
    interval: int,
) -> int:
    """Poll for new CI failures while serving Prometheus metrics."""
    host = os.getenv("CI_SENTINEL_METRICS_HOST", "127.0.0.1")
    server, thread = start_http_server(8000, addr=host)
    processed: set[tuple[int, int, int]] = set()
    print(
        f"Monitoring {repository} every {interval}s; "
        f"metrics at http://{host}:8000/metrics",
        flush=True,
    )

    try:
        with GitHubClient() as github, genai.Client() as gemini:
            while True:
                try:
                    runs = list_failed_workflow_runs(github, repository, limit=limit)
                    _analyze_runs(github, gemini, repository, runs, processed=processed)
                except GitHubApiError as exc:
                    API_ERRORS_TOTAL.labels(service="github").inc()
                    print(f"GitHub API error: {exc}", file=sys.stderr)
                time.sleep(interval)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    return 0


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
    inspect.add_argument(
        "--logs", action="store_true", help="Print shortened logs for failed jobs."
    )

    analysis = commands.add_parser("analyze", help="Diagnose failed jobs with Gemini.")
    analysis.add_argument("repository", type=_repository_arg, metavar="owner/repo")
    analysis.add_argument(
        "--limit",
        type=_limit_arg,
        choices=range(1, 6),
        default=1,
        metavar="N",
        help="Number of recent failed workflow runs to analyze (1-5; default: 1).",
    )

    monitor = commands.add_parser("serve", help="Monitor failures and expose Prometheus metrics.")
    monitor.add_argument("repository", type=_repository_arg, metavar="owner/repo")
    monitor.add_argument(
        "--limit", type=_limit_arg, choices=range(1, 6), default=1, metavar="N",
        help="Number of recent failed workflow runs to check (1-5; default: 1).",
    )
    monitor.add_argument(
        "--interval", type=_positive_int_arg, default=120, metavar="SECONDS",
        help="Polling interval in seconds (default: 120).",
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    if args.command is None:
        parser.print_help()
        return 2

    if args.command in {"analyze", "serve"} and not (
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    ):
        print("Error: Set GEMINI_API_KEY to run AI analysis.", file=sys.stderr)
        return 1

    if args.command == "serve":
        try:
            return _serve(
                args.repository, limit=args.limit, interval=args.interval,
            )
        except OSError as exc:
            print(f"Metrics server error: {exc}", file=sys.stderr)
            return 1

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

            if args.command == "analyze":
                runs = list_failed_workflow_runs(client, args.repository, limit=args.limit)
                if not runs:
                    print(f"No failed workflow runs found for {args.repository}.")
                    return 0
                with genai.Client() as gemini_client:
                    _, failed = _analyze_runs(client, gemini_client, args.repository, runs)
                return 1 if failed else 0

            runs = list_failed_workflow_runs(client, args.repository, limit=args.limit)
    except GitHubApiError as exc:
        API_ERRORS_TOTAL.labels(service="github").inc()
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1

    except GeminiAnalysisError as exc:
        API_ERRORS_TOTAL.labels(service="gemini").inc()
        print(f"Gemini analysis error: {exc}", file=sys.stderr)
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
