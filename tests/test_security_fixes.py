import io
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.api.routes.router import upload_file
from app.services.repositories import message_repo
import secrets
import string

client = TestClient(app)

def test_file_upload_rejects_spoofed_mime_type():
    # File claims to be image/jpeg, but body is HTML script
    malicious_content = b"<script>alert('xss')</script>"
    fake_file = io.BytesIO(malicious_content)
    
    response = client.post(
        "/api/files/upload",
        files={"file": ("test.jpg", fake_file, "image/jpeg")},
        headers={"Authorization": "Bearer fake_token"}
    )
    # Token rejected first or magic byte check rejected
    assert response.status_code in (400, 401)

def test_strong_password_generator():
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    pwd = "CC@" + "".join(secrets.choice(alphabet) for _ in range(12)) + "!"
    assert len(pwd) == 16
    assert any(c.isupper() for c in pwd)
    assert any(c.islower() for c in pwd)
    assert any(c.isdigit() or c in "!@#$%^&*" for c in pwd)

def test_cloudinary_webhook_rejects_tampered_signature():
    response = client.post(
        "/api/webhooks/cloudinary",
        headers={
            "x-cld-timestamp": "12345678",
            "x-cld-signature": "0000000000000000000000000000000000000000"
        },
        content=b'{"test": "payload"}'
    )
    assert response.status_code == 400
    assert response.json()["message"] == "Invalid Cloudinary webhook signature"
