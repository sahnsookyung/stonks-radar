# Backups

Nightly backups should run `scripts/backup_pg.sh` with `BACKUP_PASSPHRASE`.

Retention target:

- 7 daily local backups
- OCI volume backups while they remain within the Always Free resource envelope
- monthly restore drill to local Docker Compose

Restore drill failure blocks release.
