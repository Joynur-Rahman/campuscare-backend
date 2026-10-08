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