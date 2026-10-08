# Phase 0: Platform Setup

This phase fixes the external service contract before the FastAPI migration.
Do not commit real credentials. Copy the example values into a local `.env` file.

## 1. Clerk

Create a Clerk application with separate development and production instances.

Configure:

- Allowed frontend origins: the local frontend URL and the production frontend URL.
- Redirect URLs: the frontend sign-in and sign-up callback URLs.
- JWT issuer URL and JWKS URL for backend token verification.
- A webhook endpoint for user created, updated, and deleted events.
- Webhook signing secret stored only in the deployment secret manager.

Clerk is responsible for identity, sessions, password reset, MFA, and social login.
The FastAPI backend must never issue a second application token.

## 2. Firebase Firestore

Create a Firebase project and enable Firestore in Native mode.
Use the Firebase Emulator Suite for local development.

Planned collections:

- `users`
- `tickets`
- `ticket_history`
- `assignments`
- `feedback`
- `messages`
- `notices`
- `settings`
- `audit_logs`
- `media`

Firestore is the source of truth for CampusCare roles. New users receive the
`student` role. Only an administrator can promote a user to `faculty`, `staff`,
or `administrator`.

The backend uses the Clerk `user_id` as the Firestore user document ID.
Firestore security rules are defense in depth; the FastAPI service remains the
primary authorization boundary.

## 3. Cloudinary

Create a Cloudinary cloud and configure an upload folder such as `campuscare`.

Allowed upload types:

- JPEG, PNG, WebP
- PDF

Maximum upload size: 10 MB.

The frontend must request signed upload parameters from FastAPI. The Cloudinary
API secret must never be sent to the frontend. Firestore stores only Cloudinary
metadata such as `public_id`, secure URL, resource type, format, size, uploader,
and timestamps.

## 4. Local environment

Copy `.env.example` to `.env` and fill in provider values locally. Required
configuration groups are:

- Clerk issuer, JWKS URL, and webhook secret
- Firebase project ID and service-account values
- Firestore emulator host for local development
- Cloudinary cloud name, API key, and API secret
- CORS origins

Use the Firebase Emulator Suite for Firestore tests. Never use production data
for local development or automated tests.

## 5. Runtime target

The API is packaged as a Docker image and deployed to Google Cloud Run.
Production secrets should come from Secret Manager or the Cloud Run environment,
not from a committed file or Docker image layer.

Phase 0 exit criteria:

- Clerk application and webhook settings are configured.
- Firebase project and Firestore mode are configured.
- Local Firebase Emulator Suite can start.
- Cloudinary upload policy and folder are configured.
- Local `.env` exists but is ignored by Git.
- No credential value appears in source control.
