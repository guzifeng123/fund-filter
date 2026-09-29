# JSON Report Schema Catalog

This directory keeps versioned JSON Schema contracts and fixtures for generated local reports. These contracts make release artifacts easier to validate, archive, and consume from CI without parsing Markdown.

## Current Reports

| Report | Schema | Fixture | Contract check |
| --- | --- | --- | --- |
| Artifact alerts | `artifact-alerts.schema.json` | `artifact-alerts.fixture.json` | `scripts/check-artifact-alerts-contract.ps1` |
| Artifact manifest | `artifact-manifest.schema.json` | `artifact-manifest.fixture.json` | `scripts/check-artifact-manifest-contract.ps1` |
| Backup | `backup-report.schema.json` | `backup-report.fixture.json` | `scripts/check-backup-report-contract.ps1` |
| Cleanup | `cleanup-report.schema.json` | `cleanup-report.fixture.json` | `scripts/check-cleanup-report-contract.ps1` |
| Contract summary | `contract-summary-report.schema.json` | `contract-summary-report.fixture.json` | `scripts/check-contract-summary-report-contract.ps1` |
| Migration | `migration-report.schema.json` | `migration-report.fixture.json` | `scripts/check-migration-report-contract.ps1` |
| Smoke | `smoke-report.schema.json` | `smoke-report.fixture.json` | `scripts/check-smoke-report-contract.ps1` |
| Visual check | `visual-check-report.schema.json` | `visual-check-report.fixture.json` | `scripts/check-visual-check-report-contract.ps1` |

All contract checks are auto-discovered by `scripts/check-report-contracts.ps1`, and `scripts/check-all.ps1` runs that batch entrypoint.

## Naming

- Schema files use `<report-name>.schema.json`.
- Fixture files use `<report-name>.fixture.json`.
- Contract check scripts use `scripts/check-<report-name>-contract.ps1`.
- Report schemas use `schema_version` as the top-level version field. Start at `1` and only increment when consumers need migration logic.
- JSON Schema files currently target draft-07 because the workspace already has AJV v6 available.

## Validation Layers

Each report contract should have two validation layers:

1. JSON Schema validation through `scripts/validate-json-schema.js`.
2. Report-specific consistency checks in its PowerShell contract script.

Examples of consistency checks:

- Count fields match array lengths.
- `ok` agrees with failure lists.
- File names match paths.
- Generated command arguments match command fields.

## Adding A Report

1. Add `packages/contracts/<report-name>.schema.json`.
2. Add `packages/contracts/<report-name>.fixture.json`.
3. Add `scripts/check-<report-name>-contract.ps1`.
4. Run the contract script against the fixture.
5. If the producing script can generate a report without external services, run it and validate with `-ReportPath` or the equivalent parameter.
6. Confirm `scripts/check-report-contracts.ps1` discovers the schema and contract script. It scans `packages/contracts/*-report.schema.json` plus `artifact-alerts.schema.json` and `artifact-manifest.schema.json`, then expects `scripts/check-<schema-base-name>-contract.ps1`.
7. Update `docs/待完成与版本任务规划.md` with the completed item and the next useful follow-up.

## Commands

```powershell
node scripts\validate-json-schema.js packages\contracts\smoke-report.schema.json packages\contracts\smoke-report.fixture.json
.\scripts\check-smoke-report-contract.ps1
.\scripts\check-report-contracts.ps1
.\scripts\check-report-contracts.ps1 -JsonReportPath output/checks/report-contracts-summary.json
.\scripts\check-report-contracts.ps1 -JsonReportPath output/checks/report-contracts-summary.json -MarkdownReportPath output/checks/report-contracts-summary.md
.\scripts\check-all.ps1 -SkipBuild -CheckOpenApiDrift -OpenApiDiffPath output/checks/openapi.diff
```

When `-JsonReportPath` is provided without `-MarkdownReportPath`, the batch script also writes a readable Markdown summary next to the JSON file by appending `.md` to the JSON path.
