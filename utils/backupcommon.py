"""Pieces shared by the FTP and S3 backup tools."""

import os
from dataclasses import dataclass, field


@dataclass
class BackupSummary:
    uploaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    would_upload: list[str] = field(default_factory=list)  # dry runs only
    chmod_failed: list[str] = field(default_factory=list)  # FTP only: files whose permissions could not be set


def local_files(local_dir: str) -> list[str]:
    """Names of the regular, non-hidden files directly in ``local_dir`` (not recursive), sorted."""
    return sorted(
        name
        for name in os.listdir(local_dir)
        if not name.startswith(".") and os.path.isfile(os.path.join(local_dir, name))
    )


def clean_subdirectory(subdirectory: str) -> str:
    """Normalise a destination subdirectory, refusing one that is empty, absolute, or would leave the base."""
    parts = [p for p in subdirectory.strip().split("/") if p]
    if not parts or subdirectory.strip().startswith("/") or ".." in parts or "." in parts:
        raise ValueError(f"invalid subdirectory {subdirectory!r}: give a relative name like 'my-stream-2026'")
    return "/".join(parts)
