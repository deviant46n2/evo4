# Reversible workspace sample data

Evo's desktop client can insert a small illustrative dataset so a new installation does not present every workspace as an empty shell.

## What is inserted

- **Memory:** five sample records covering project direction, hardware/model baseline, approval policy, and reproducible measurement.
- **Memory candidates:** two tentative records with moderate confidence, available for the normal accept/reject workflow.
- **Agents:** three historical example runs (successful inspection, an approval-checkpoint example, and a failed build example) with recorded tool-event rows. No agent is launched, no file is written, and no command is executed.
- **Experiments:** three illustrative run records grouped into two configurations, including successful and failed examples.
- **Hardware history:** four synthetic telemetry samples per sample experiment, so historical charts have points to render. These are not readings from the current machine.

No demo conversation or live hardware metric is fabricated. The Hardware live cards continue to call the real local telemetry sampler. Sample experiment telemetry appears only in historical charts and is marked as sample data.

## Provenance and storage

Every inserted record has a stable demo marker:
- memories and candidates use source `demo-seed`;
- agent run metadata contains `demo_seed: true`;
- experiment `config_json` contains `demo_seed: true`;
- resource samples inherit demo provenance through their experiment foreign key.

The records are written into the same configured SQLite database used by the corresponding real workspaces. This lets the user inspect how normal UI browsing, candidate review, archive/supersession, agent-event history, experiment aggregation, and hardware-history views operate against persisted records.

Seeding is idempotent: repeated requests do not create duplicates. Clearing deletes only marked demo rows, their associated tool events, memory relations/FTS entries, and telemetry samples. It does not delete user-created records or real experiment runs. If a user accepts a demo memory candidate, it remains marked with the demo source and is removed by the demo cleanup operation.

## Controls and API

Each data workspace displays a **SAMPLE DATA** banner with:
- **Load sample data** — inserts missing sample records.
- **Remove samples** — asks for confirmation and removes only demo-marked records.

Local API routes:
- `GET /api/v1/demo/status`
- `POST /api/v1/demo/seed`
- `DELETE /api/v1/demo/seed`

The UI labels sample records explicitly. Sample values must never be presented as actual benchmark results, live hardware readings, user memories, or real agent work.
