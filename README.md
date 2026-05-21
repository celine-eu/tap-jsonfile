# tap-jsonfile

Singer tap that reads JSON files from local filesystem or S3-compatible storage (including MinIO).

Built with the [Meltano Singer SDK](https://sdk.meltano.com).

## Features

- Glob patterns to match files across directories (`data/**/*.json`)
- S3 and MinIO support via [fsspec](https://filesystem-spec.readthedocs.io/) / [s3fs](https://s3fs.readthedocs.io/)
- Automatic schema inference by sampling the first N files
- JSON, JSON arrays, and JSONL formats detected automatically
- Incremental sync: tracks file content hashes in Singer state, skips unchanged files on subsequent runs
- Adds `_sdc_source_file` to every record for lineage

## Configuration

| Setting       | Required | Default    | Description                                              |
|---------------|----------|------------|----------------------------------------------------------|
| `paths`       | Yes      | —          | List of glob patterns for JSON files (local or `s3://…`) |
| `stream_name` | No       | `records`  | Name of the output Singer stream                        |
| `samples`     | No       | `20`       | Number of files to sample for schema inference           |

### S3 / MinIO credentials

Set these environment variables (standard AWS naming, also accepts `S3_*` prefix):

| Variable                | Description                                  |
|-------------------------|----------------------------------------------|
| `AWS_ACCESS_KEY_ID`     | Access key (or `S3_ACCESS_KEY_ID`)           |
| `AWS_SECRET_ACCESS_KEY` | Secret key (or `S3_SECRET_ACCESS_KEY`)       |
| `AWS_ENDPOINT_URL`      | Custom endpoint for MinIO (or `S3_ENDPOINT_URL`) |

## Usage

### Standalone

```bash
# Local files
tap-jsonfile --config '{"paths": ["data/**/*.json"]}' > output.jsonl

# S3 / MinIO (credentials via env vars)
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_ENDPOINT_URL=https://minio.example.com
tap-jsonfile --config '{"paths": ["s3://bucket/prefix/**/*.json"]}'
```

### Incremental sync

Pass state from a previous run to skip unchanged files:

```bash
tap-jsonfile --config config.json > output.jsonl 2>/dev/null

# Extract state for next run
grep '"type":"STATE"' output.jsonl | tail -1 | python3 -c \
  "import sys,json; print(json.dumps(json.loads(sys.stdin.read())['value']))" > state.json

# Next run skips files whose content hash hasn't changed
tap-jsonfile --config config.json --state state.json
```

### With Meltano

```bash
uv tool install meltano
meltano install
meltano run tap-jsonfile target-jsonl
```

See `meltano.yml` for the default configuration (`paths: ["data/**/*.json"]`).

## Development

Prerequisites: Python 3.10+, [uv](https://docs.astral.sh/uv/)

```bash
uv sync
uv run pytest          # 41 tests
uv run tap-jsonfile --about
```
