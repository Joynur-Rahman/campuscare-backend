# CampusCare Backend API

A high-performance FastAPI backend service powering **CampusCare**—a comprehensive campus issue reporting, facility management, and ticket resolution platform.

Built with Python 3.12, FastAPI, Supabase (PostgreSQL with Row Level Security), Clerk Authentication, and Cloudinary.

---

## 🚀 Features

- **Robust Ticket Lifecycle Management**: Full state transition workflows (`submitted` ➔ `assigned` ➔ `in_progress` ➔ `resolved` / `reopened` / `escalated`) backed by PostgreSQL transactional RPCs.
- **Threaded Ticket Messaging**: Real-time collaborative chat on tickets between students, assigned technicians, and administrators with role-aware access controls.
- **Role-Based Access Control (RBAC)**: Enforced roles (`student`, `faculty`, `staff` / technician, `administrator`) with dependency-level route guards.
- **Automatic Account Linking**: Seamlessly associates administrator pre-provisioned technician and staff accounts to Clerk accounts on their first sign-in.
- **Cloud Media Management**: Signed direct uploads and secure file management using Cloudinary.
- **Audit Logging & Governance**: Structured JSON logging with request correlation IDs, audit trail logging, and retention policies.
- **Security & Reliability**: SlowAPI rate limiting, strict security headers (CSP, HSTS, X-Frame-Options), and configurable CORS origins.

---

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| **Language & Runtime** | Python 3.12 |
| **Framework** | FastAPI, Starlette, Uvicorn |
| **Authentication** | [Clerk](https://clerk.com) (RS256 JWT via JWKS) |
| **Database** | [Supabase](https://supabase.com) (PostgreSQL, PostgREST, RLS) |
| **Media Storage** | [Cloudinary](https://cloudinary.com) |
| **Rate Limiting** | SlowAPI |
| **Containerization** | Docker, Docker Compose |
| **Testing** | Pytest, FastAPI TestClient |

---

## 📁 Project Structure

```text
campuse_care-backend/
├── app/
│   ├── api/
│   │   ├── deps.py              # Authentication & role dependencies
│   │   └── routes/
│   │       └── router.py        # Central API router & endpoints
│   ├── core/
│   │   ├── clerk.py             # Clerk JWT verification via JWKS
│   │   ├── cloudinary.py        # Cloudinary signature generation
│   │   ├── config.py            # Pydantic Settings configuration
│   │   ├── logger.py            # Structured logger & Correlation ID middleware
│   │   └── supabase.py          # Supabase client singleton
│   ├── models/                  # Database model placeholders
│   ├── schemas/
│   │   └── __init__.py          # Pydantic request/response schemas & Enums
│   ├── services/
│   │   ├── notifications.py     # Notification dispatcher service
│   │   └── repositories.py      # Data access layer (Supabase tables & RPCs)
│   └── main.py                  # FastAPI application entry point & middleware
├── docs/                        # Project architectural documentation
├── supabase/
│   └── schema.sql               # Full PostgreSQL schema, tables, policies & RPCs
├── tests/
│   └── test_app.py              # Integration tests
├── Dockerfile                   # Production-ready Docker containerfile
├── docker-compose.yml           # Compose service definition
├── seed.py                      # Database seeder for departments & categories
└── requirements.txt             # Python project dependencies
```

---

## ⚙️ Environment Configuration

Create a `.env` file in the root of `campuse_care-backend/` based on `.env.example`:

```ini
# Environment
APP_ENV=development

# CORS Configuration
CORS_ORIGINS=http://localhost:5173,http://localhost:3000

# Clerk Authentication Configuration
CLERK_ISSUER=https://<your-clerk-instance>.clerk.accounts.dev
CLERK_JWKS_URL=https://<your-clerk-instance>.clerk.accounts.dev/.well-known/jwks.json
CLERK_SECRET_KEY=sk_test_<your_clerk_secret_key>
CLERK_WEBHOOK_SECRET=whsec_<your_clerk_webhook_secret>

# Supabase Configuration
SUPABASE_URL=https://<your-project-id>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
SUPABASE_DB_URL=postgresql://postgres:<password>@db.<your-project-id>.supabase.co:5432/postgres

# Cloudinary Configuration
CLOUDINARY_CLOUD_NAME=<your_cloud_name>
CLOUDINARY_API_KEY=<your_api_key>
CLOUDINARY_API_SECRET=<your_api_secret>
CLOUDINARY_UPLOAD_FOLDER=campuscare
```

---

## 🗄️ Database Setup (Supabase)

1. Open your project in the [Supabase Dashboard](https://supabase.com/dashboard).
2. Navigate to the **SQL Editor**.
3. Paste and run the contents of [`supabase/schema.sql`](supabase/schema.sql).
4. This provisions:
   - Tables (`users`, `tickets`, `ticket_history`, `messages`, `notices`, `settings`, `audit_logs`, `departments`, `categories`, etc.)
   - Row-Level Security (RLS) policies protecting tables from direct public exposure
   - Stored procedures: `create_ticket_with_history`, `assign_ticket_with_history`, `update_ticket_with_history`, and `submit_ticket_feedback`
5. Seed initial departments and complaint categories:
   ```bash
   python seed.py
   ```

---

## 🏃 Running the Application

### Option 1: Full-Stack Docker Compose (Backend + Frontend)

To run both the **FastAPI backend** and **React frontend** together:

1. Place `docker-compose.yml` in the parent directory outside `campuse_care-backend` where both frontend and backend repositories reside:
   ```text
   project-root/
   ├── docker-compose.yml
   ├── campuse_care-backend/
   └── campuscare-react/ (or campuscare-frontend/)
   ```
2. Ensure both `.env` files are configured in their respective folders (`campuse_care-backend/.env` and `campuscare-react/.env`).
3. From the parent directory, launch both containers:
   ```bash
   # Build and start both services in the background
   docker compose up -d --build

   # View live logs
   docker compose logs -f

   # Check container status
   docker compose ps
   ```

- **Backend API**: `http://localhost:8000` (Swagger docs: `http://localhost:8000/docs`)
- **Frontend App**: `http://localhost:5173`

---

### Option 2: Running Backend Standalone with Docker

To build and run only the backend container:

```bash
cd campuse_care-backend

# Build the Docker image
docker build -t campuscare-backend .

# Run the container with environment variables
docker run -d -p 8000:8000 --env-file .env --name campuscare-backend campuscare-backend
```

### Option 3: Local Python Environment

```bash
# 1. Create and activate a virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## 📖 API Documentation & Endpoints

Interactive Swagger documentation is available once the server is running:
- **Swagger UI**: [`http://localhost:8000/docs`](http://localhost:8000/docs)
- **ReDoc**: [`http://localhost:8000/redoc`](http://localhost:8000/redoc)

### Key Endpoints

| Category | Method | Endpoint | Description |
|---|---|---|---|
| **Health** | `GET` | `/health` | Service health status check |
| **Health** | `GET` | `/ready` | Supabase database connectivity check |
| **Auth** | `GET` | `/api/auth/me` | Fetch and synchronize current user profile |
| **Auth** | `GET` | `/api/auth/session` | Validate Clerk JWT session |
| **Tickets** | `GET` | `/api/tickets` | List tickets (filtered by user role/ownership) |
| **Tickets** | `POST` | `/api/tickets` | Create a new ticket with history |
| **Tickets** | `PUT` | `/api/tickets/{id}/status` | Update ticket status with remarks & media |
| **Messages** | `GET` | `/api/messages/thread/{id}` | Fetch chat thread history for a ticket |
| **Messages** | `POST` | `/api/messages` | Send a message to a ticket thread or user |
| **Staff** | `GET` | `/api/staff/technicians` | List available technicians |
| **Admin** | `GET` | `/api/admin/users` | List all users across roles |
| **Admin** | `POST` | `/api/admin/users` | Create/pre-provision technician or staff accounts |
| **Admin** | `PUT` | `/api/admin/users/{id}/role`| Update user role |
| **Media** | `POST` | `/api/files/upload/signature`| Generate signed upload parameters for Cloudinary |
| **Audit** | `GET` | `/api/audit-log` | View system activity and security audit trail |

---

## 🧪 Testing

Run automated tests inside Docker or locally:

```bash
# Inside Docker:
docker compose exec -e PYTHONPATH=. backend pytest

# Locally:
pytest
```

---

## 🔒 Security Best Practices

- **Zero Secret Commits**: `.env` and sensitive keys are explicitly ignored in `.gitignore`.
- **Server-Only Database Policies**: All Supabase tables use RLS set to `server_only`, preventing direct client manipulation and guaranteeing that the FastAPI backend acts as the sole authorization gateway.
- **Signed Cloudinary Uploads**: Direct client uploads require temporary cryptographic signatures generated exclusively by the backend.
- **Tamper-Proof Audit Logging**: Administrative role changes, ticket resolution, and sensitive events are recorded automatically in `audit_logs`.
