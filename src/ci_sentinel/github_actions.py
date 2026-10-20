"""GitHub Actions utilities and validated repository identifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass

_OWNER_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")
_REPO_PATTERN = re.compile(r"[A-Za-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class Repository:
    """An already validated GitHub owner/repository identifier."""

    owner: str
    name: str

    def __post_init__(self) -> None:
        """Enforce the same validation for direct construction and parsing."""
        if not _OWNER_PATTERN.fullmatch(self.owner) or not _REPO_PATTERN.fullmatch(self.name):
            raise ValueError("Repository contains invalid owner or repository characters.")
        if self.name in {".", ".."}:
            raise ValueError("Repository name cannot be '.' or '..'.")

    @classmethod
    def parse(cls, value: str) -> Repository:
        """Validate owner/repo syntax without making an HTTP request."""
        parts = value.split("/")
        if len(parts) != 2:
            raise ValueError("Repository must use the 'owner/repo' format.")

        owner, name = parts
        return cls(owner=owner, name=name)

    def __str__(self) -> str:
        return f"{self.owner}/{self.name}"
