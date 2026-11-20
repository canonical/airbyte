# Ubuntu archive downloads source connector (proof of concept)

This directory contains `source-ubuntu-archive-downloads`, a Python connector built on the Airbyte CDK. It reads the Ubuntu archive Apache access logs that are stored in Swift and emits one record per download of a package in a configured package set (for example CUDA). Totals are left to the destination.

## Streams

There is one stream per configured package set, named after the set.

| Column        | Type        | From                                                          |
| ------------- | ----------- | ------------------------------------------------------------- |
| `timestamp`   | timestamptz | the request time in the log line                              |
| `package`     | string      | `name` in `name_version_arch.deb`                             |
| `version`     | string      | `version`, URL-decoded (`%7e` becomes `~`)                    |
| `arch`        | string      | `arch`                                                        |
| `bytes`       | integer     | the response size, null when the log has `-`                  |
| `source`      | string      | the container's `source` in the config: `archive_server`, `ports_server` or `cloud_mirror` |
| `prodstack`   | string      | the container's `prodstack` in the config, for example `ps5`  |
| `container`   | string      | the Swift container the log object is in                      |
| `log_object`  | string      | the log object name                                           |
| `line_number` | integer     | the line in the decompressed log object                       |

The primary key is `prodstack`, `container`, `log_object`, `line_number`, since the same container name can exist on more than one Prodstack. Use **Incremental | Append + Deduped** so that reading a log object again overwrites the rows with the same line numbers instead of adding them (see the note on regenerated logs below).

A line becomes a record when it is a `GET` with status `200` for a `.deb` path, and the package name matches one of the set's glob patterns. The client IP is never read out of the line.

Daily totals per package are one query over a stream's table:

```sql
SELECT timestamp::date AS date, package, version, arch,
       count(*) AS downloads, sum(bytes) AS bytes
FROM cuda
GROUP BY date, package, version, arch;
```

## How a sync works

1. List the objects in each configured container and keep the access logs (`...access.log-YYYYMMDD.gz`) dated on or after `start_date`.
2. Skip the objects already read, per Prodstack and container.
3. For each remaining object, in date order: stream it from Swift, gunzip it, filter its lines (a fast byte check on the raw line, then the full parse), then emit the matches and save state once the whole object has been read.

The state for each container is saved under `<prodstack>/<container>`, for example `ps5/archive-server-logs`, and has two parts:

- `completed_through`: a date. Every object dated on or before it has been read.
- `read`: the objects dated after `completed_through` that have already been read, each with its last-modified time when it was read.

`completed_through` never moves into the last `lookback_days` days. Each sync checks the objects in that window against `read`. It reads any object that is missing from `read` because it arrived late, and any object whose last-modified time has changed because it was rewritten. So `read` only ever holds a few days of objects.

An object's records are sent, and its state saved, only after the whole object has been read. Until then its matches are held in a temporary file, so memory stays flat. If an object can't be read, for example a truncated gzip, it sends no records: the stream logs an error naming it and reads the rest. It keeps that container's `completed_through` below the object's date, then fails the stream at the end, so the sync shows as failed and the next one retries the object. A corrupt object fails every sync until it's uploaded again or removed.

A log that is uploaded again is assumed to have the same lines in the same order, as when an incomplete upload is replaced by the full log: its rows are replaced by line number. If a log is regenerated with different content, rows for lines that no longer match are left behind. Use **Clear data** on the connection to rebuild the tables in that case. Each stream reads the logs separately, so two package sets download each log object twice.

Raw lines hold client IPs, so they are never logged. Each object logs one info line with the lines read, matched rows and lines that failed to parse, and each stream logs one info line at the end of a sync with the package names it matched and a count for each. Candidate lines in an unexpected format and containers with no objects named like dated access logs are logged as warnings.

## Configuration

| Field          | Description                                                                                       | Required |
| -------------- | ------------------------------------------------------------------------------------------------- | -------- |
| `storage`      | `swift`, with one Keystone v3 endpoint and its credentials per Prodstack, or `local` (a directory, for testing only) | Yes |
| `containers`   | The Swift containers that hold the access logs, each as `{name, source, prodstack}`               | Yes      |
| `start_date`   | The earliest log date to read, `YYYY-MM-DD`                                                       | Yes      |
| `lookback_days`| How many days back each sync rechecks for objects not read yet (default 2); set above the upload lag | No    |
| `package_sets` | A list of `{name, match}`, where `match` holds glob patterns on the whole package name            | Yes      |

## Local development

```bash
poetry install --with dev
make test          # ruff, unit tests, and check/discover/read against the mock archives
make read          # print the records the mock archives produce
make mock-archives # regenerate integration_tests/mock_archives
make build         # build airbyte/source-ubuntu-archive-downloads:dev
```

To run against Swift, start from `integration_tests/sample_config.json`, fill in the endpoints, credentials and container names, save it as `secrets/config.json` and run `make read CONFIG="--config secrets/config.json"`.

### Mock archives

`integration_tests/generate_mock_archives.py` writes four containers (`mock-archive-servers-a`, `mock-archive-servers-b`, `mock-ports-servers` and `mock-cloud-mirrors`) with three days of access logs each, plus error logs and an uncompressed live log that must be skipped. Each access log has the same hand-written cases (matches, near misses, other statuses and methods, a pool directory decoy, an IPv6 client, a URL-encoded version) mixed in with seeded noise.

They assume every container uses the same object layout and log line format.

## Not covered yet

- An optional country column, which would need a GeoIP data source and must not store client IPs.
