from __future__ import annotations

from ci_sentinel.cli import main


def test_version_exits_successfully() -> None:
    assert main(["--version"]) == 0


def test_no_arguments_returns_usage_error() -> None:
    assert main([]) == 2


def test_unknown_option_returns_usage_error() -> None:
    assert main(["--unknown"]) == 2


def test_help_exits_successfully() -> None:
    assert main(["--help"]) == 0
