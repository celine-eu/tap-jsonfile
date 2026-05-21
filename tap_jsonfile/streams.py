"""Stream type classes for tap-jsonfile."""

from __future__ import annotations

import hashlib
import sys
from typing import TYPE_CHECKING, Any

from singer_sdk.streams import Stream

from tap_jsonfile.client import parse_json_content
from tap_jsonfile.storage import Storage

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from collections.abc import Iterable

    from singer_sdk.helpers.types import Context


class JsonFileStream(Stream):
    """Stream that reads records from JSON files matched by glob patterns.

    Tracks file content hashes in Singer state so unchanged files are
    skipped on subsequent runs.
    """

    name = "records"
    replication_key = None

    @override
    def get_records(
        self,
        context: Context | None,
    ) -> Iterable[dict[str, Any]]:
        """Yield records from new or modified JSON files.

        Files whose SHA-256 hash matches the value stored in state from a
        previous run are skipped.  State is updated after each file so that
        partial runs still make progress.
        """
        prev_hashes: dict[str, str] = dict(
            self.stream_state.get("file_hashes", {}),
        )
        current_hashes: dict[str, str] = {}
        skipped = 0

        for pattern in self.config["paths"]:
            store = Storage(pattern)
            for path in store.glob():
                try:
                    raw = store.read_bytes(path)
                except OSError:
                    self.logger.warning("Failed to read %s, skipping", path)
                    continue

                file_hash = hashlib.sha256(raw).hexdigest()

                if prev_hashes.get(path) == file_hash:
                    current_hashes[path] = file_hash
                    skipped += 1
                    continue

                try:
                    records = parse_json_content(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    self.logger.warning("Failed to parse %s, skipping", path)
                    continue

                for record in records:
                    record["_sdc_source_file"] = path
                    yield record

                current_hashes[path] = file_hash
                self.stream_state["file_hashes"] = current_hashes

        self.stream_state["file_hashes"] = current_hashes
        if skipped:
            self.logger.info("Skipped %d unchanged files", skipped)
