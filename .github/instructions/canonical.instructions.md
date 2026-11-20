---
description: 'Ensure connector version fields stay consistent across metadata.yaml and pyproject.toml, including canonicalImageTag, in every PR.'
applyTo: 'airbyte-integrations/connectors/source-*/metadata.yaml, airbyte-integrations/connectors/source-*/pyproject.toml, airbyte-integrations/connectors/destination-*/metadata.yaml, airbyte-integrations/connectors/destination-*/pyproject.toml'
---

# Connector Canonical Version Consistency Instructions

## Purpose

Use this instruction whenever a connector's `metadata.yaml` and/or `pyproject.toml` is created, reviewed, or modified, for this company-forked Airbyte environment.

Primary objective:
- Keep connector version fields mutually consistent across `pyproject.toml` and `metadata.yaml`, including `canonicalImageTag`, in every PR that touches connector code, manifest, or dependencies

## Glossary

- `dockerImageTag`: The released Docker image version for the connector, defined in `metadata.yaml`
- `canonicalImageTag`: The standardized, fork-specific release tag in `metadata.yaml` that identifies the canonical connector image version to publish and deploy, typically derived from `dockerImageTag` plus a fork-specific suffix (e.g. `<dockerImageTag>-canonical-<fork-version>`)
- `pyproject.toml` version: The `[tool.poetry].version` field, present only for connectors with custom Python code

## Version consistency requirement (mandatory, every PR)

1. `pyproject.toml` `[tool.poetry].version` must equal `metadata.yaml` `dockerImageTag`
2. `metadata.yaml` `canonicalImageTag` must be present and must be based on the same `dockerImageTag`, using the fork's canonical suffix convention
3. If the connector's code, manifest, or dependencies change in the PR, all three values (`pyproject.toml` version, `dockerImageTag`, and `canonicalImageTag`) must be bumped together in that same PR — never update only one of them
4. If `pyproject.toml` does not exist for the connector (manifest-only, no custom Python), this check applies only to `dockerImageTag` and `canonicalImageTag` alignment in `metadata.yaml`
5. Never leave `dockerImageTag`, `canonicalImageTag`, and `pyproject.toml` version out of sync at the end of a PR; treat any mismatch as a blocking condition
6. If the canonical tag format is not fully specified in context, ask the prompter for the exact expected format before finalizing

## Workflow

1. Identify the connector's current `dockerImageTag`, `canonicalImageTag`, and (if present) `pyproject.toml` version
2. Confirm whether this PR changes connector code, manifest, or dependencies; if so, determine the correct new version per project versioning conventions
3. Update `pyproject.toml` version, `dockerImageTag`, and `canonicalImageTag` together so all three remain consistent
4. Validate that the canonical image tag matches the fork's required registry/namespace/tagging convention
5. Do not mark work complete if canonical tagging is missing, malformed, or inconsistent with fork conventions, or if any of the three values are out of sync

## Blocking conditions

Mark as blocked if any condition applies:

1. `pyproject.toml` version, `metadata.yaml` `dockerImageTag`, and `metadata.yaml` `canonicalImageTag` are not mutually in sync
2. Any of the three values were not all bumped together when connector code, manifest, or dependencies changed in this PR
3. `canonicalImageTag` is missing, malformed, or inconsistent with fork conventions
4. Canonical tag format is not specified and cannot be confirmed with the prompter

## Quality gates before completion

1. `pyproject.toml` version (when present), `metadata.yaml` `dockerImageTag`, and `metadata.yaml` `canonicalImageTag` match and were updated together in this PR
2. `canonicalImageTag` follows the fork's required tagging convention

## Completion output contract

When this instruction applies, include a version sync status note stating the final `pyproject.toml` version, `dockerImageTag`, and `canonicalImageTag` values, and confirming they match, or explaining why they could not be reconciled.
