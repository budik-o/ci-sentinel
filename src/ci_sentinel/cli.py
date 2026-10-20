"""CLI entry point."""

from __future__ import annotations

import argparse

from ci_sentinel import __version__


def main(argv: list[str] | None = None) -> int:
    """Parse CLI options and return a conventional process exit code."""
    parser = argparse.ArgumentParser(
        prog="ci-sentinel",
        description="Analyze failed GitHub Actions jobs and expose diagnostics metrics.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    try:
        parser.parse_args(argv)
    except SystemExit as exc:
        # argparse raises SystemExit for --help, --version, and invalid options.
        return exc.code if isinstance(exc.code, int) else 1

    # No analysis or service commands yet.
    parser.print_help()
    return 2
