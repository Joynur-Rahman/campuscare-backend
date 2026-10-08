# CampusCare Backend Tasks

This checklist is based on `CampusCare_SRS_v1.0.pdf` and `FASTAPI_API_LIST.pdf`.
The backend owns CampusCare data and authorization rules. Clerk owns identity,
sessions, password recovery, MFA, and social login. Supabase stores CampusCare
data, while Cloudinary stores uploaded media and attachments.

Phase 0 setup details are documented in [`PHASE_0_SETUP.md`](PHASE_0_SETUP.md).

## Phase 0 - Decisions and prerequisites

- [x] Confirm FastAPI as the backend framework and Docker as the runtime target.
- [x] Confirm Clerk as the authentication provider instead of local passwords/JWT issuance.
- [ ] Create the Clerk application and configure allowed origins, redirect URLs, and environments.
- [x] Use Supabase as the application database.
- [x] Use Cloudinary for images, documents, profile photos, and resolution attachments.
- [x] Store CampusCare roles in Supabase; optionally mirror them to Clerk public metadata for frontend display.
- [x] Define the role values exactly: `student`, `faculty`, `staff`, `administrator`.
- [x] Define the production database and media providers: Supabase and Cloudinary.
- [x] Set the default role for new users to `student`; only administrators can promote users.
- [x] Set the upload policy to images/PDF only, with a maximum size of 10 MB.
- [x] Configure a local Supabase development project or Supabase CLI workflow.
- [x] Select Google Cloud Run as the production Docker deployment target.

## Phase 1 - Foundation and project structure

- [x] Create the FastAPI application package and domain router layout.
- [x] Add environment-based settings, Dockerfile, Docker Compose, `.dockerignore`, and a health endpoint.
- [x] Split the initial implementation into `api`, `core`, `models`, `schemas`, and `services` modules matching the API contract.
- [x] Add Supabase project configuration and initialize the database client once through a cached provider.
- [x] Add Supabase repositories so route handlers do not contain database/query details.
- [x] Add Cloudinary configuration and a media service for validated uploads and controlled access.
- [x] Add structured application logging and request correlation IDs.
- [x] Add CORS configuration driven by environment variables.
- [x] Add a non-secret `.env.example` covering Clerk, Supabase, Cloudinary, and CORS settings.
- [x] Add Supabase local development configuration for database and authentication-adjacent testing.

## Phase 2 - Clerk authentication and user synchronization

- [x] Add `CLERK_ISSUER`, `CLERK_JWKS_URL`, and `CLERK_SECRET_KEY` settings.
- [x] Implement a FastAPI bearer-token dependency that validates Clerk JWT signature, issuer, audience, expiry, and subject.
- [x] Read the `Authorization: Bearer <token>` header through FastAPI's header dependency.
- [x] Replace local `/api/auth/register` and password verification with Clerk-compatible session behavior.
- [x] Implement `/api/auth/me`, `/api/auth/session`, `/api/auth/logout`, role lookup, and role verification against the Clerk identity.
- [x] Add a Supabase user record keyed by Clerk `user_id`, storing display name, email, phone, role, and timestamps.
- [x] Add Clerk webhook handling for user created, updated, and deleted events.
- [x] Verify webhook signatures and make synchronization idempotent.
- [x] Reject missing, expired, malformed, or revoked Clerk tokens with `401` responses.
- [x] Reject valid users without the required CampusCare role with `403` responses.

Acceptance criteria:

- A Clerk-authenticated request reaches `current_user` without the backend creating a second token.
- A user cannot choose or elevate their own role through a profile endpoint.
- Local user records remain synchronized after a Clerk profile update or deletion.

## Phase 3 - Core complaint workflow

- [x] Add complaint creation and owner-scoped complaint listing.
- [x] Add administrator assignment to staff members.
- [x] Add assigned-staff status updates, resolution remarks, and status history.
- [x] Add resolved-complaint feedback with one feedback record per complaint and owner protection.
- [x] Add complaint categories and departments as managed records rather than free-form strings.
- [x] Validate lifecycle transitions: submitted -> assigned -> in progress -> resolved, with controlled reopen/escalate paths.
- [x] Store assignment history, resolution timestamp, resolver, and resolution attachments.
- [x] Prevent students/faculty from reading another user's complaints, messages, or feedback.
- [x] Ensure administrators can monitor all complaints without bypassing audit logging.

Acceptance criteria:

- Students and faculty see only their own complaints.
- Staff see only complaints assigned to them.
- Administrators can assign complaints only to active staff users.
- Every status change records actor, previous status, new status, remarks, and timestamp.
- Feedback is accepted only from the complaint owner after resolution and only once.

## Phase 4 - Contract coverage

- [x] Add user profile, staff, assignment, message, notice, settings, audit, diagnostics, and file-upload endpoints.
- [x] Keep streaming endpoints compatible with the contract using newline-delimited event responses.
- [x] Expose OpenAPI documentation and stable `/api/...` route prefixes.
- [x] Implement the complete authentication contract: password reset delegation, admin email lookup, and role verification.
- [x] Implement confidential-ticket flows.
- [x] Implement ticket appointment and acknowledge flows.
- [x] Implement ticket follow/join flows.
- [x] Implement ticket similar-search, reopen, escalate, and resolve flows.
- [x] Implement technician and campus-member administration with administrator-only access.
- [x] Implement admin conversations, replies, read state, and thread authorization.
- [x] Implement notice creation/end lifecycle and settings persistence.
- [x] Implement audit-log streaming with authorization and retention rules.
- [x] Add bounded offset/limit pagination, filtering, and sorting to collection endpoints.
- [x] Return consistent error schemas for validation, authentication, authorization, not-found, and conflict cases.

## Phase 5 - Supabase and Cloudinary storage

- [x] Create the core Supabase tables for `users`, `tickets`, `ticket_history`, `feedback`, `ticket_followers`, `ticket_supporters`, `ticket_appointments`, `ticket_media`, `messages`, `notices`, and `audit_logs`.
- [x] Define UUIDs, timestamps, ownership fields, status values, foreign keys, and feedback constraints consistently.
- [x] Add database transactions for assignment, status changes, resolution, and one-time feedback creation.
- [x] Add indexes for owner, assignee, department, status, and ticket-history queries.
- [x] Add Row Level Security policies as defense in depth; all business authorization remains in FastAPI.
- [x] Validate upload size, MIME type, extension, and ownership before Cloudinary uploads.
- [x] Use a 10 MB maximum for complaint, profile, and resolution uploads.
- [x] Generate signed Cloudinary upload parameters without exposing the API secret to clients.
- [x] Store only Cloudinary `public_id`, secure URL, resource type, format, size, and uploader metadata in Supabase.
- [x] Add controlled media deletion when a complaint or attachment is removed according to retention rules.
- [x] Add Cloudinary webhook handling if asynchronous transformation or moderation is enabled.
- [x] Document Supabase service-key handling for local development, Docker, and production secret managers.

## Phase 6 - Security and operations

- [x] Add rate limiting for authentication-adjacent and upload endpoints.
- [x] Add security headers, trusted-host configuration, and production CORS restrictions.
- [x] Add notification interfaces for email, in-app, assignment, and status-change events.
- [x] Add Supabase backup, restore, retention, and data-export procedures.
- [x] Add health/readiness checks that verify Supabase connectivity and required Clerk/Cloudinary configuration.
- [x] Add monitoring for Supabase errors, Cloudinary upload failures, webhook failures, and authorization denials.

## Phase 7 - Verification and release

- [ ] Add integration tests for Clerk token validation using mocked JWKS/token fixtures.
- [ ] Add Supabase repository tests using a local Supabase database or isolated test database.
- [ ] Add Cloudinary upload tests using mocked signed-parameter and deletion responses.
- [ ] Add tests for role isolation, complaint creation, assignment, resolution, reopen, escalation, and feedback.
- [ ] Add tests for webhook signature validation and idempotent user synchronization.
- [ ] Add tests for file validation, message privacy, administrator controls, and audit entries.
- [x] Run formatting, linting, type checking, and the full test suite in Docker with Supabase local development support.
- [x] Add a Docker Compose development profile and a production deployment profile.
- [ ] Add API examples for Clerk bearer authentication and the complaint lifecycle.
- [ ] Verify OpenAPI routes against `FASTAPI_API_LIST.pdf` before release.

## Deferred enhancements from the SRS

- [ ] Automated complaint categorization.
- [ ] Analytics dashboard for trends, departments, categories, and resolution time.
- [ ] Mobile application support.
- [ ] Advanced monthly, department-performance, and historical reports.