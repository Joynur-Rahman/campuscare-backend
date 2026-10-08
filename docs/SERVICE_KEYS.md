# Supabase Service Key Handling

This document describes how the `SUPABASE_SERVICE_ROLE_KEY` is handled across environments.

## Security Warning
The Service Role Key has administrative privileges and bypasses Row Level Security (RLS). 
**NEVER expose this key to the frontend application.**

## Local Development
For local development, store the key in your local `.env` file:
```env
SUPABASE_URL=http://localhost:54321
SUPABASE_SERVICE_ROLE_KEY=ey...
```

## Docker Compose
When running via Docker Compose, inject the secret using an `.env` file or environment variables. 
Ensure the `.env` file is excluded from version control via `.gitignore`.

## Production
In production, you MUST use a secure secret manager to inject the `SUPABASE_SERVICE_ROLE_KEY` at runtime.
- AWS: Use AWS Secrets Manager or Parameter Store.
- GCP: Use Google Cloud Secret Manager.
- Vercel/Render: Set the key securely in the platform's Environment Variables UI.

## Application Usage
The backend accesses this key securely via `app.core.config.settings` and strictly uses it only for:
1. Validating JWTs with the database.
2. Server-side operations where RLS needs to be bypassed (e.g. automated background jobs).
3. Secure endpoints explicitly marked for `administrator` role.
