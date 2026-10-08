# CampusCare Operations & Disaster Recovery

## 1. Database Backups and Restore (Supabase)

CampusCare uses Supabase (PostgreSQL) as its primary database.

### Automated Backups
- Supabase Pro/Enterprise plans include **Point-in-Time Recovery (PITR)**.
- Automated daily logical backups are taken and retained for 7-30 days depending on the project plan.
- **Action:** Ensure PITR is enabled in the Supabase Dashboard under `Database -> Backups`.

### Manual Backups
To take a manual logical backup of the schema and data:
```bash
supabase db dump --data-only -f backup_data.sql
supabase db dump -f backup_schema.sql
```

### Restore Procedure
To restore a backup to a clean database:
```bash
psql -h db.[PROJECT-REF].supabase.co -p 5432 -d postgres -U postgres -f backup_schema.sql
psql -h db.[PROJECT-REF].supabase.co -p 5432 -d postgres -U postgres -f backup_data.sql
```
For PITR restores, use the Supabase Dashboard to restore the project to a specific minute.

## 2. Data Retention and Export
- **Audit Logs:** Audit logs are kept for 90 days by default. The `DELETE /api/audit-log` endpoint cleans up older logs.
- **Exporting Data:** The `GET /api/audit-log/export` streams audit logs as NDJSON.
- To export complaints or tickets in bulk, administrators should use a direct SQL query or a reporting replica.

## 3. Monitoring and Logging
The backend uses structured JSON logging. These logs are stdout/stderr and collected by Google Cloud Run.

**Key Monitoring Metrics:**
- **Authorization Denials:** Logged as `WARNING` with `type="authorization_denial"` and a `403` HTTP status.
- **Supabase Errors:** Logged as `ERROR` with `type="database_error"`.
- **Cloudinary/Upload Failures:** Logged as `ERROR` with `type="upload_failure"`.
- **Webhook Failures:** Logged as `ERROR` with `type="webhook_failure"`.

*Operators should set up log-based metrics in GCP/AWS to trigger alerts when the frequency of `ERROR` logs spikes.*
