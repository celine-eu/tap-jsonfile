"""Storage abstraction using fsspec."""

from __future__ import annotations

import os
import typing as t

from fsspec.core import url_to_fs


class Storage:
    """Filesystem abstraction to list and open files using fsspec."""

    def __init__(self, path_glob: str) -> None:
        """Initialize storage for a glob pattern, detecting S3 from the prefix."""
        self.path_glob = path_glob

        if path_glob.startswith("s3://"):
            storage_options: dict[str, t.Any] = {
                "key": os.getenv("S3_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID"),
                "secret": os.getenv("S3_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY"),
                "client_kwargs": {
                    "endpoint_url": os.getenv("S3_ENDPOINT_URL") or os.getenv("AWS_ENDPOINT_URL"),
                },
            }
        else:
            storage_options = {}

        self.fs, _ = url_to_fs(path_glob, **storage_options)

    def glob(self) -> list[str]:
        """Return matching file paths (always including protocol prefix for remote)."""
        paths: list[str] = self.fs.glob(self.path_glob)

        if self.path_glob.startswith("s3://"):
            return [f"s3://{p}" if not p.startswith("s3://") else p for p in paths]

        return paths

    def open(self, path: str, mode: str = "r") -> t.IO:
        """Open a file handle with fsspec."""
        return self.fs.open(path, mode)

    def read_bytes(self, path: str) -> bytes:
        """Read entire file content as bytes."""
        with self.fs.open(path, "rb") as f:
            return f.read()
