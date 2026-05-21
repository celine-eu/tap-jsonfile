"""JsonFile tap class."""

from __future__ import annotations

import sys

from singer_sdk import Tap
from singer_sdk import typing as th

from tap_jsonfile.client import infer_schema
from tap_jsonfile.streams import JsonFileStream

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override


class TapJsonFile(Tap):
    """Singer tap that reads JSON files from local or S3-compatible storage."""

    name = "tap-jsonfile"

    config_jsonschema = th.PropertiesList(
        th.Property(
            "paths",
            th.ArrayType(th.StringType),
            required=True,
            description="List of glob patterns for JSON files (local or s3://...)",
        ),
        th.Property(
            "stream_name",
            th.StringType,
            default="records",
            description="Name of the output Singer stream",
        ),
        th.Property(
            "samples",
            th.IntegerType,
            default=20,
            description="Number of files to sample for schema inference",
        ),
    ).to_dict()

    @override
    def discover_streams(self) -> list[JsonFileStream]:
        """Return a list of discovered streams.

        Returns:
            A list containing a single JsonFileStream with an inferred schema.
        """
        schema = infer_schema(dict(self.config))
        stream_name = self.config.get("stream_name", "records")
        return [JsonFileStream(self, name=stream_name, schema=schema)]


if __name__ == "__main__":
    TapJsonFile.cli()
