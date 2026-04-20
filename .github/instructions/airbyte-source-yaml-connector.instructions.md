---
description: 'Build and review Airbyte manifest-only source connectors end-to-end, including implementation, testing, documentation, and merge readiness checks.'
applyTo: 'airbyte-integrations/connectors/source-*/manifest.yaml, airbyte-integrations/connectors/source-*/acceptance-test-config.yml, airbyte-integrations/connectors/source-*/metadata.yaml, airbyte-integrations/connectors/source-*/README.md, airbyte-integrations/connectors/source-*/CONTRIBUTING.md, docs/integrations/sources/*.md'
---

# Airbyte YAML connector instructions

## Purpose

Use this instruction for both development and review of YAML-based Airbyte source connectors.

Primary objective:
- Ensure connector correctness, reliability, and maintainability.

Secondary objective:
- Ensure tests, docs, and contribution guidance are complete.

## Operating mode

Choose mode based on user intent.

### Development mode

Use when the user asks to create, update, or fix a connector.

### Review mode

Use when the user asks for review, QA, readiness, or risk assessment.

## Scope

Apply to manifest-only connectors where behavior is declaratively defined in YAML.

Before implementation, ensure required API context is available:
- If API docs are not provided, ask the prompter for API documentation or a concrete endpoint list for streams to sync.
- Skim provided docs before designing streams, auth, pagination, and cursors.
- If any required behavior is unclear, ask follow-up questions and do not make assumptions.

If custom Python is required:
- Keep YAML as the primary behavior definition.
- Add Python only for non-declarative gaps.
- Add unit tests for all custom logic.

## Required artifacts for new or major connector changes

1. `manifest.yaml`
2. `acceptance-test-config.yml`
3. `metadata.yaml`
4. `README.md`
5. Connector icon when missing
6. `docs/integrations/sources/<connector>.md`
7. Connector-level `CONTRIBUTING.md`

## Development Workflow

### 1. API and stream design

1. Identify authentication, pagination, rate limits, and failure classes.
2. Build an explicit endpoint inventory and assign stream sync mode per endpoint.
3. Define every stream explicitly in the manifest.
   - Do not embed stream definitions in inline structures.
   - Reuse shared component definitions, but keep each stream as an explicit top-level stream entry.
4. Select stable primary keys and cursor fields:
   - Prefer native stable keys from the API.
   - If no globally unique stable key exists, build a deterministic composite key from stable business fields
      and generate an airbyte_unique_id hash from that composite key.
5. Prefer server-side filtering and bounded windows where supported.
6. Prefer real incremental cursoring whenever API semantics support monotonic filtering or ordered windows.
   - Use incremental append + deduped when a stable primary key and reliable cursor semantics are both available.
   - Fall back to full refresh only when incremental correctness cannot be guaranteed; document the reason.
7. Define retry and backoff by transient and permanent failure classes:
   - Ignore non-retriable resource conditions such as 404 and 409.
   - Treat 403 as conditional: retry only when response indicates rate limiting; otherwise treat as
      non-retriable permission or policy failure.
   - Retry 429 responses and honor server retry headers when available.
   - Retry 502, 503, and 504 with constant backoff of 60 seconds.
   - Cap retries to a reasonable bounded limit (for example, 5) to prevent runaway sync durations.

### 2. Manifest implementation

1. Reuse shared definitions for requester, auth, and error handling.
2. Configure a reliable check stream.
3. Ensure each stream is declared explicitly.
4. Ensure schema, extractor, key strategy, and partitions are coherent.
5. For incremental streams:
   - Match cursor to API filter semantics.
   - Apply lower and upper bounds correctly.
   - Prevent cursor drift and duplicate amplification.
   - Prefer incremental append + deduped when key and cursor guarantees are valid.
6. For substreams:
   - Define parent-child partitioning explicitly.
   - Use scalable cursor and state behavior.

### 3. Tests

1. Update acceptance test config for spec validation and relevant coverage.
2. Use explicit bypass reasons only when credentials are unavailable.
3. Keep strictness high unless justified.
4. If custom Python exists, add unit tests for:
   - Error and retry classification
   - Pagination and cursor boundaries
   - Record transformation and key generation
5. Prefer integration acceptance coverage when sandbox credentials exist.
6. Do not claim tests passed unless they were executed.

### 4. Documentation

1. Update `README.md` with:
   - Scope and behavior summary
   - Configuration fields
   - Stream inventory and sync modes
   - Local build and validation steps
   - Known limitations and tradeoffs
2. Update user-facing connector docs in integrations sources.
3. Follow Airbyte environment-aware documentation conventions where needed.

### 5. Contribution guidance

Create or update connector-level `CONTRIBUTING.md` with:

1. Prerequisites and setup
2. Build and test commands
3. Secrets handling and config examples
4. Validation sequence: spec, check, discover, read
5. PR expectations and reviewer checklist
6. Common failure modes and debugging guidance

## Review workflow

### Review order

1. Data correctness
2. Incremental and state safety
3. Reliability and retry behavior
4. Scalability and API efficiency
5. Security and secret handling
6. Test adequacy
7. Documentation and contribution completeness

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

## Quality gates before completion

1. Manifest structure is valid and internally coherent.
2. Acceptance test config aligns with available credentials and expected coverage.
3. Metadata is complete and consistent with connector identity.
4. README and user docs match actual connector behavior.
5. `CONTRIBUTING.md` is actionable for another engineer.
6. Validation commands are run or blockers are explicitly documented.

## Completion output contract

Always end with:

1. Summary of changes or findings
2. Files touched
3. Commands run and outcomes
4. What was unverified and why
5. Residual risks and next recommended steps
