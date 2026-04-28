---
description: 'Build and review Airbyte manifest-only source connectors end-to-end, including implementation, testing, documentation, and merge readiness checks.'
applyTo: 'airbyte-integrations/connectors/source-*/manifest.yaml, airbyte-integrations/connectors/source-*/acceptance-test-config.yml, airbyte-integrations/connectors/source-*/metadata.yaml, airbyte-integrations/connectors/source-*/README.md, airbyte-integrations/connectors/source-*/CONTRIBUTING.md, airbyte-integrations/connectors/source-*/Makefile, airbyte-integrations/connectors/source-*/erd/*.dbml, docs/integrations/sources/*.md'
---

# Airbyte Source YAML Connector Instructions

## Purpose

Use this instruction for both development and review of manifest-only Airbyte source connectors.

Primary objective:
- Ensure connector correctness, reliability, and maintainability

Secondary objective:
- Ensure tests, docs, and contribution guidance are complete and accurate

## Operating mode

Select a mode based on user intent and execute only the relevant workflow.

### Development mode

Use when the user asks to create, update, or fix a connector.

### Review mode

Use when the user asks for review, QA, readiness, or risk assessment.

## Agent execution rules

- Use imperative, deterministic behavior
- Treat all MUST and DO NOT statements as mandatory
- Do not assume API behavior, endpoint versions, or canonical image tag formats
- If required information is missing, stop and ask for it
- Do not mark work complete when blocking conditions are present
- Parallel sub-agents may be used for read-only discovery tasks only when two or more independent discovery tasks are required
   - Recommended parallel tasks include, but are not limited to:
      - Rate-limit and quota policy extraction
      - Stream-specific API documentation checks
      - Authentication and authorization requirement analysis
      - Endpoint inventory and stream mapping extraction
      - Pagination and cursor pattern analysis by endpoint
      - Error-classification and retry-header behavior analysis
      - Schema and field-constraint extraction from API references
   - Consolidate sub-agent outputs into one reconciled result before implementation
   - If sub-agents produce conflicting information, treat the task as blocked until resolved with source docs or prompter clarification

## Scope

Apply to manifest-only source connectors where behavior is declaratively defined in YAML.

Before implementation, ensure required API context is available:
- If API docs are not provided, ask the prompter for API documentation or a concrete endpoint list for streams to sync
- Skim provided docs before designing streams, auth, pagination, API versioning, and cursors
- If any required behavior is unclear, ask follow-up questions and do not make assumptions

If custom Python is required:
- Keep YAML as the primary behavior definition
- Add Python only for non-declarative gaps
- Add unit tests for all custom logic

## Glossary

- ERD: Entity Relationship Diagram; a schema-level model of streams/tables and their relationships
- CDK: Connector Development Kit used by Airbyte to implement and run connectors
- canonicalImageTag: The standardized, fork-specific release tag in `metadata.yaml` that identifies the canonical connector image version to publish and deploy

## Required inputs

Before implementation or review, obtain:

1. API documentation or a concrete endpoint list for all planned streams
2. Source API version details per endpoint
3. Canonical image tagging format for this company-forked Airbyte environment
4. Airbyte CDK version target and compatibility context for upstream Airbyte 1.7

If any required input is missing, ask the prompter and mark the task blocked until clarified.

## Prerequisite checks

Confirm these before implementation or review:

1. Source API version is identified and validated for each endpoint used by the connector
2. Metadata canonical image tagging format is known and will be applied correctly in `metadata.yaml`
3. Airbyte CDK version is compatible with upstream Airbyte version 1.7
4. For this company-forked Airbyte context, canonical image tagging is mandatory for connector metadata

If any prerequisite cannot be confirmed from provided context, ask the prompter before proceeding.

## Required artifacts for new or major connector changes

Ensure all artifacts below are present and coherent:

1. `manifest.yaml`
2. `acceptance-test-config.yml`
3. `metadata.yaml`
4. `README.md`
5. Connector icon when missing
   - Preferred format: SVG
   - Recommended dimensions: 128 x 128 pixels
   - Aspect ratio: 1:1 (square)
   - Design: transparent background with clear readability at small UI sizes
   - Optimize for fast UI loading; target icon file size under 100 KB when feasible
   - If an icon cannot be created, mark icon delivery as non-blocking with explicit justification in the completion report
6. `docs/integrations/sources/<connector>.md`
7. Connector-level `CONTRIBUTING.md`
8. Connector-root `Makefile` with common local development and validation commands
9. ERD definition file at `erd/source.dbml`
10. Unit test suite under `unit_tests/` with realistic fixtures and stream coverage
11. Integration test suite under `integration_tests/` with config, catalog, state, and expected output artifacts

## Development workflow (development mode)

### 1. API and stream design

1. Identify authentication, pagination, rate limits, failure classes, and source API version semantics
   - Confirm the connector uses the correct source API version for each endpoint
   - Do not mix incompatible versioned endpoints unless explicitly documented and justified
2. Build an explicit endpoint inventory and assign stream sync mode per endpoint
3. Define every stream explicitly in the manifest
   - Do not embed stream definitions in inline structures
   - Reuse shared component definitions, but keep each stream as an explicit top-level stream entry
4. Select stable primary keys and cursor fields:
   - Prefer native stable keys from the API
   - If no globally unique stable key exists, build a deterministic composite key from stable business fields and generate an `airbyte_unique_id` (md5) hash from that composite key
5. Prefer server-side filtering and bounded windows where supported
6. Use real incremental cursoring whenever API semantics support monotonic filtering or ordered windows
   - Use incremental append + deduped when a stable primary key and reliable cursor semantics are both available
   - Fall back to full refresh only when incremental correctness cannot be guaranteed; document the reason
7. Define retry and backoff by transient and permanent failure classes:
   - First use source API documentation to determine retriable and non-retriable status codes for each endpoint
   - If API documentation is missing or incomplete, apply this fallback policy:
      - Ignore non-retriable resource conditions such as 404 and 409
      - Treat 403 as conditional: retry only when response indicates rate limiting; otherwise treat as non-retriable permission or policy failure
      - Retry 429 responses and honor server retry headers when available
      - Retry 502, 503, and 504 with constant backoff of 60 seconds
      - Cap retries to a bounded limit (for example, 20) to prevent runaway sync durations

### 2. Manifest implementation

1. Reuse shared definitions for requester, auth, and error handling
2. Configure a reliable check stream
3. Ensure each stream is declared explicitly
4. Ensure schema, extractor, key strategy, and partitions are coherent
5. For incremental streams:
   - Match cursor to API filter semantics
   - Apply lower and upper bounds correctly
   - Prevent cursor drift and duplicate amplification
   - Use incremental append + deduped when key and cursor guarantees are valid
6. For substreams:
   - Define parent-child partitioning explicitly
   - Specify parent stream, parent key, partition field identifier, and request injection mapping
   - Use partitioning only for parameterized data slices; do not use it as a replacement for pagination or time-based incremental sync
   - If multiple partition routers are configured, evaluate Cartesian product growth and bound request volume
   - If grouping partition routers are used, verify incremental/state behavior remains stable across runs
   - Use scalable cursor and state behavior

### 3. Tests

1. Create both unit and integration tests for new connectors and major stream behavior changes
2. Use the same testing depth and structure expected from mature manifest-only connectors
3. Never create placeholder or cosmetic tests (for example, `assert True`) to satisfy coverage requirements
4. Never write tests that encode known broken behavior as the expected result
   - If connector behavior is broken, fix the connector first, or mark the task blocked with explicit evidence
   - Do not weaken assertions or remove checks just to make tests pass
5. Update acceptance test config for spec validation and relevant coverage
6. Use explicit bypass reasons only when credentials are unavailable
7. Keep strictness high unless justified
8. Prefer integration acceptance coverage when sandbox credentials exist
9. Do not claim tests passed unless they were executed

#### CI test expectations

1. Assume CI will run all available connector tests for the connector, including Connector QA checks and tests in `unit_tests/` and `integration_tests/`
2. For local Connector Acceptance runs, use `airbyte-ci` for Airbyte version 1.7 and prepare the environment with non-interactive commands:
   ```bash
   cd airbyte-ci/connectors/pipelines/
   poetry install
   ```
3. Provide connector config as `.secrets/config.json` in the connector root before running acceptance commands
4. Run connector acceptance using the exact connector slug from `metadata.yaml`; replace `<connector>` in the command below with that slug:
   ```bash
   poetry run airbyte-ci connectors --name source-<connector> test
   ```
5. If `.secrets/config.json` is unavailable, explicitly document the blocker and do not claim local acceptance execution succeeded

#### Unit test expectations

1. Maintain a connector-level `unit_tests/` package with at least:
   - `conftest.py` for shared source construction, manifest path resolution, common config, and reusable fixtures
   - `pyproject.toml` for the test environment and dependencies
   - Focused test modules such as `test_source.py`, `test_streams.py`, `test_pagination.py`, and `test_components.py` when custom components exist
2. Keep test data in `unit_tests/responses/*.json` and load fixtures from files rather than hardcoding large payloads
3. Use HTTP mocking patterns that validate endpoint paths and query parameters, including:
   - Success responses
   - 4xx/5xx error classification behavior
   - Pagination boundaries and final-page behavior
4. Validate stream behavior per stream, including:
   - Record counts and selected record content
   - Number of HTTP calls where it reveals pagination or substream fan-out behavior
   - Incremental cursor handling and lower-bound application
5. Cover substream and partition routers with realistic parent-child slices
6. For custom components, add deterministic unit tests for extractor/transformer/router logic with mocked responses
7. Include retry-relevant tests for 403/404/409/429/5xx semantics based on connector policy

#### Integration test expectations

1. Maintain `integration_tests/` with realistic execution artifacts, including:
   - `sample_config.json`
   - `invalid_config.json` and other validation-failure config variants
   - `configured_catalog.json`
   - `sample_state.json` and edge-case state (for example, abnormal or future cursor values)
   - `expected_records.jsonl` when deterministic expected output assertions are used
   - A small, windowed start date in test configs (for example, recent lookback windows) so integration runs complete quickly and reduce rate-limit or quota failures
2. Ensure integration coverage validates:
   - Check/read behavior with valid config
   - Failure behavior with invalid auth/domain/config
   - Incremental state progression and partitioned state handling
3. Keep integration scaffolding executable and meaningful
   - If a test file is a harness placeholder, replace it with real assertions before completion
4. Ensure integration test fixtures and catalogs are synchronized with the current manifest stream set and cursor strategy

#### Test quality and execution requirements

1. Tests must validate real connector logic, not only import paths or object construction
2. Assertions must be specific enough to catch regressions in URL building, query params, cursor math, and partitioning
3. Prefer small, composable fixtures and shared builders over duplicated inline setup
4. If exact behavior cannot be validated due to missing API details, ask the prompter for missing details instead of guessing
5. Include executed test commands and outcomes in the completion report

### 4. Documentation

1. Update `README.md` with:
   - Scope and behavior summary
   - Configuration fields
   - Stream inventory and sync modes
   - Local build and validation steps
   - Known limitations and tradeoffs
   - Common structure for manifest-only connectors:
      - Connector overview (name, purpose, notable behavior)
      - Building the docker image
      - Creating credentials
      - Local development
      - Running as a docker container (`spec`, `check`, `discover`, `read`)
      - Running the CI test suite (`airbyte-ci`)
      - Publishing/versioning notes when applicable
2. Update user-facing connector docs in integrations sources
3. Follow Airbyte environment-aware documentation conventions where needed
4. Enforce documentation secrets safety:
   - Never include real secrets in docs (API keys, tokens, passwords, client secrets, private keys, account identifiers, or tenant-specific internal URLs)
   - Use placeholders for all sensitive fields (for example, `<api_key>`, `<client_id>`, `<client_secret>`, `<subdomain>`)
   - Keep credential examples in clearly labeled example blocks and state that values are non-production placeholders
   - Redact any sample logs or payload snippets that could expose sensitive headers or credentials

### 5. Contribution guidance

Create or update connector-level `CONTRIBUTING.md` with:

1. Prerequisites and setup
2. Build and test commands
3. Secrets handling and config examples
4. Validation sequence: spec, check, discover, read
5. PR expectations and reviewer checklist
6. Common failure modes and debugging guidance
7. Use this common structure for manifest-only connectors:
   - Overview and connector-specific behaviors
   - Key files and repository layout
   - Setup and local environment
   - Secrets handling and test configuration
   - Validation sequence with expected outcomes
   - Pull request checklist and quality gates
   - Troubleshooting playbook (auth, rate limit, timeout, pagination/state issues)
8. Include a mandatory contributor check that docs and examples are secrets-safe before opening a PR:
   - Confirm no real credentials are present in `README.md`, `CONTRIBUTING.md`, or integration/source docs
   - Confirm `.secrets/config.json` is local-only and never copied into tracked docs
   - Confirm all config examples use placeholders and not reusable tokens

### 6. ERD generation

After connector implementation and test execution:

1. Generate or update `erd/source.dbml` to reflect the final stream and relationship model
2. Keep ERD naming and relationship style consistent with existing connector ERD conventions
3. Ensure primary keys and major foreign-key relationships are represented
4. If relationship certainty is incomplete, annotate conservatively in the PR notes rather than inventing links

### 7. Connector Makefile

Create or update a connector-root `Makefile` with common commands.

1. Include standard targets:
   - `build`
   - `spec`
   - `check`
   - `discover`
   - `read`
   - `unit-test`
   - `test`
2. Include practical defaults for common variables:
   - `IMAGE`
   - `CONFIG`
   - `CATALOG`
   - `PYTHON`
   - `DAGGER`
   - `AIRBYTE_CI`
3. Ensure `help` output documents available targets and expected input files
4. Execute required workflow targets and verify they work as expected: `build`, `spec`, `check`, `discover`, `read`, `unit-test`, and `test`
5. Ensure `read` mounts config and integration artifacts correctly
6. Ensure `unit-test` runs pytest from `unit_tests/`
7. Ensure `test` runs connector acceptance through `airbyte-ci`

### 8. Metadata canonical image tagging

For this company-forked Airbyte environment:

1. Always add canonical image tagging in `metadata.yaml`
2. Validate that the canonical image tag matches the fork's required registry/namespace/tagging convention
3. If canonical tag format is not fully specified in context, ask the prompter for the exact expected format before finalizing
4. Do not mark work complete if canonical tagging is missing, malformed, or inconsistent with fork conventions

## Review workflow (review mode)

### Review order

1. Data correctness
2. Incremental and state safety
3. API version and compatibility checks
4. Reliability and retry behavior
5. Scalability and API efficiency
6. Security and secret handling
7. Test adequacy
8. Documentation and contribution completeness

### Findings format

For each finding, provide:

1. Severity: Critical, High, Medium, Low
2. Location: file and exact section or key
3. Risk: production impact
4. Evidence: why behavior is unsafe or incorrect
5. Minimal fix recommendation

If no findings:

1. State no blocking findings
2. List residual risks
3. List what could not be fully validated

### Blocking conditions

Mark as blocked if any condition applies:

1. Incorrect cursor semantics or unsafe state progression
2. Primary key strategy risks collisions or data corruption
3. Retry policy can cause severe stalls or non-termination
4. Manifest structure is invalid
5. Docs materially misrepresent behavior
6. Required tests are missing without justified bypass
7. Stream definitions are embedded in ways that prevent explicit review of each stream
8. API behavior was assumed without docs or user confirmation
9. Source API version prerequisite is unmet or endpoint versioning is inconsistent
10. Metadata canonical image tagging prerequisite is unmet, missing, malformed, or not aligned to company-fork conventions
11. Airbyte CDK compatibility prerequisite is unmet for upstream Airbyte 1.7
12. ERD artifact `erd/source.dbml` is missing or materially out of sync with implemented streams
13. Tests are placeholders, non-executable, or intentionally aligned to broken connector behavior
14. Connector-root `Makefile` is missing or does not expose common build/spec/check/discover/read/unit-test/test commands

## Quality gates before completion

1. Manifest structure is valid and internally coherent
2. Acceptance test config aligns with available credentials and expected coverage
3. Metadata is complete and consistent with connector identity
4. Metadata includes canonical image tagging in the expected format for connector release and company-fork conventions
5. Airbyte CDK version compatibility is confirmed against upstream Airbyte version 1.7
6. Source API version usage is verified across streams and matches documented endpoint versions
7. README and user docs match actual connector behavior
8. `CONTRIBUTING.md` is actionable for another engineer
9. Validation commands are run or blockers are explicitly documented
10. ERD file `erd/source.dbml` is generated or updated to match the implemented schema and relationships
11. Unit and integration tests are present, executable, and assert correct connector behavior rather than broken behavior
12. Connector-root `Makefile` is present and supports the standard local workflow commands

## Completion output contract

Always end with the following sections, in this order:

1. Summary of changes or findings
2. Files touched
3. Commands run and outcomes
4. What was unverified and why
5. Residual risks and next recommended steps
6. ERD status: explicitly state whether `erd/source.dbml` was created or updated, and why if not
7. Canonical image tagging status: explicitly state what tag was set in `metadata.yaml`, or why it could not be set

If any blocking condition is active, clearly label the final status as `Blocked` and list the unresolved blockers first.
