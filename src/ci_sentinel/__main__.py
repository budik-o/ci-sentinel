"""Enable `python -m ci_sentinel`."""

from __future__ import annotations

from ci_sentinel.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
