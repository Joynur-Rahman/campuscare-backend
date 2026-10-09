from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "campuscare-api"}


def test_readiness() -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "supabase"}


def test_protected_profile_requires_bearer_token() -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["message"] == "Bearer token required"


def test_clerk_webhook_rejects_unsigned_payload() -> None:
    response = client.post("/api/webhooks/clerk", json={"type": "user.created"})

    assert response.status_code == 400
    assert response.json()["message"] == "Invalid webhook signature"


def test_documented_core_routes_are_registered() -> None:
    routes = {route.path for route in app.routes}

    assert "/api/tickets" in routes
    assert "/api/tickets/{ticket_id}/status" in routes
    assert "/api/tickets/similar" in routes
    assert "/api/tickets/confidential" in routes
    assert "/api/tickets/confidential/stream" in routes
    assert "/api/tickets/{ticket_id}/follow" in routes
    assert "/api/tickets/{ticket_id}/join" in routes
    assert "/api/tickets/{ticket_id}/appointment" in routes
    assert "/api/tickets/{ticket_id}/acknowledge" in routes
    assert "/api/tickets/{ticket_id}/resolve" in routes
    assert "/api/tickets/{ticket_id}/reopen" in routes
    assert "/api/tickets/{ticket_id}/escalate" in routes
    assert "/api/assignments/tickets/{ticket_id}/assign" in routes
    assert "/api/files/upload" in routes
    assert "/api/files/{media_id}" in routes
    assert "/api/files/upload/signature" in routes


def test_domain_restriction_rejects_non_iiitg_self_registration(monkeypatch) -> None:
    from fastapi import HTTPException
    import pytest
    from app.api.deps import resolve_or_link_user

    class DummyUserRepo:
        def get_by_clerk_id(self, uid):
            return None

    class DummyTable:
        def select(self, *args):
            return self
        def eq(self, *args):
            return self
        def maybe_single(self):
            return self
        def execute(self):
            return type("Res", (), {"data": None})()

    class DummySb:
        def table(self, name):
            return DummyTable()

    monkeypatch.setattr("app.api.deps.user_repo", DummyUserRepo())
    monkeypatch.setattr("app.api.deps.get_supabase", lambda: DummySb())

    with pytest.raises(HTTPException) as exc_info:
        resolve_or_link_user("user_external", email_hint="outsider@gmail.com")
    assert exc_info.value.status_code == 403
    assert "restricted to @iiitg.ac.in" in exc_info.value.detail


def test_domain_restriction_allows_pre_created_staff(monkeypatch) -> None:
    from app.api.deps import resolve_or_link_user

    pre_created_profile = {
        "clerk_id": "staff_temp_123",
        "email": "electrician@gmail.com",
        "full_name": "Electrician Ramesh",
        "role": "staff"
    }

    class DummyUserRepo:
        def get_by_clerk_id(self, uid):
            return None

    class DummyTable:
        def select(self, *args):
            return self
        def eq(self, *args):
            return self
        def maybe_single(self):
            return self
        def update(self, *args):
            return self
        def execute(self):
            return type("Res", (), {"data": pre_created_profile})()

    class DummySb:
        def table(self, name):
            return DummyTable()

    monkeypatch.setattr("app.api.deps.user_repo", DummyUserRepo())
    monkeypatch.setattr("app.api.deps.get_supabase", lambda: DummySb())

    result = resolve_or_link_user("clerk_worker_real", email_hint="electrician@gmail.com")
    assert result["role"] == "staff"
    assert result["email"] == "electrician@gmail.com"