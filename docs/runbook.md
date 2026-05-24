# Runbooks

## Provider Quota Exhausted

Turn on the provider kill switch, let jobs move to `quota_wait` or retry/dead-letter, and serve latest snapshots with stale warning if needed.

## Bad Source Data

Disable the source, mark affected facts/events under review, publish correction/retraction if public snapshots were affected, then replay ingestion after policy review.

## Public Event Correction

Create a correction log row, publish a new correction snapshot, roll forward affected object snapshots, and keep prior immutable snapshots internally.

## Backend Outage

Leave public app served from snapshots. Restore API/worker stack from Docker Compose, verify Postgres, then resume jobs.

## Snapshot Publish Failure

Do not update the latest manifest until candidate validation passes and version files are copied. Inspect the snapshot artifact and published snapshot volumes, disk watermark, and job error, then replay `snapshot_publish`.

## Snapshot Rollback

Rollback changes the mutable manifest pointer only. Do not delete immutable snapshots during incident response.

## DB Restore

Run `scripts/restore_pg.sh` against a clean local database first. Release is blocked if restore drill fails.

## Suspected Prompt Injection

Quarantine source document, disable LLM jobs for that source, review invocations by hash, and require manual review for derived facts.

## Source-Policy Violation

Disable public display for affected facts/events, publish correction if necessary, update `source_policy_decision`, and rerun snapshots.

## Disk Near Full

70% warning, 80% critical, 90% degraded/read-only. Prune candidates, logs, and old local backups according to retention policy.
