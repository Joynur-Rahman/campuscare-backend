import hashlib
import hmac
import json
import logging
import random
import secrets
import re
import string
import uuid
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from svix.webhooks import Webhook, WebhookVerificationError

from app.core.config import settings
from app.core.cloudinary import delete_media, signed_upload_parameters, upload_media
from app.core.supabase import get_supabase
from app.schemas import (
    AcknowledgeRequest,
    AdminUserCreate,
    AppointmentProposal,
    AppointmentResponse,
    AssignmentRequest,
    FeedbackCreate,
    LoginRequest,
    MessageCreate,
    NoticeCreate,
    Role,
    RoleUpdate,
    RoleVerification,
    SettingsUpdate,
    TicketAction,
    TicketCreate,
    TicketMergeRequest,
    TicketStatus,
    TicketUpdate,
    UserCreate,
)
from app.api.deps import current_supabase_user, require_supabase_role, resolve_or_link_user
from app.core.clerk import get_current_claims
from app.services.notifications import notification_service
from app.services.repositories import (
    department_repo, category_repo,
    user_repo, ticket_repo, appointment_repo, feedback_repo,
    media_repo, message_repo, notice_repo, audit_repo, settings_repo
)


from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

router = APIRouter()

@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "campuscare-api"}

@router.get("/ready")
def readiness() -> dict[str, str]:
    try:
        user_repo.get_technicians(0, 1)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Supabase is unavailable") from exc
    return {"status": "ready", "database": "supabase"}

@router.post("/api/auth/register", status_code=410)
@limiter.limit("5/minute")
def register(request: Request, _: UserCreate) -> None:
    raise HTTPException(410, "Registration is handled by Clerk")

@router.post("/api/auth/login")
@limiter.limit("5/minute")
def login(request: Request, _: LoginRequest) -> None:
    raise HTTPException(410, "Login is handled by Clerk")

@router.post("/api/auth/password-reset")
@limiter.limit("5/minute")
def password_reset(request: Request) -> None:
    raise HTTPException(410, "Password reset is handled by Clerk")

@router.get("/api/auth/me")
def me(email: str | None = None, name: str | None = None, claims: dict = Depends(get_current_claims)) -> dict:
    user_id = claims["sub"]
    # SECURITY: Ignore client-supplied query parameters to prevent account takeover.
    # Email is strictly extracted from verified JWT claims or Clerk API lookup.
    email_hint = claims.get("email")
    return resolve_or_link_user(user_id, email_hint=email_hint)

@router.get("/api/auth/session")
def session_check(claims: dict = Depends(get_current_claims)) -> dict[str, object]:
    return {"authenticated": True, "user_id": claims["sub"]}

@router.get("/api/auth/admin-emails")
def admin_emails(_: dict = Depends(require_supabase_role(Role.administrator))) -> dict[str, list[str]]:
    return {"emails": user_repo.get_admin_emails()}

@router.post("/api/auth/verify-role")
def verify_role(data: RoleVerification, user: dict = Depends(current_supabase_user)) -> dict[str, object]:
    return {"verified": user.get("role") == data.role.value, "role": user.get("role")}

@router.post("/api/webhooks/clerk")
async def clerk_webhook(request: Request) -> dict[str, str]:
    try:
        event = Webhook(settings.clerk_webhook_secret).verify(await request.body(), request.headers)
    except WebhookVerificationError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from exc

    event_type = event.get("type")
    data = event.get("data", {})
    clerk_id = data.get("id")
    if not clerk_id:
        raise HTTPException(status_code=400, detail="Webhook payload has no user id")

    if event_type == "user.deleted":
        user_repo.delete(clerk_id)
        return {"status": "deleted"}
    if event_type not in {"user.created", "user.updated"}:
        return {"status": "ignored"}

    email = next((item.get("email_address", "") for item in data.get("email_addresses", []) if item.get("id") == data.get("primary_email_address_id")), "").lower().strip()
    phone = next((item.get("phone_number") for item in data.get("phone_numbers", []) if item.get("id") == data.get("primary_phone_number_id")), None)
    
    existing = user_repo.get_by_clerk_id(clerk_id)
    if not existing and email:
        sb_existing = get_supabase().table("users").select("*").eq("email", email).maybe_single().execute()
        if sb_existing and sb_existing.data:
            existing = sb_existing.data

    if not existing:
        # Only allow auto-provisioning via webhook for official IIITG domain
        if not (email.endswith("@iiitg.ac.in") or email.endswith(".iiitg.ac.in")):
            return {"status": "ignored_non_iiitg_domain"}

    profile = {
        "clerk_id": clerk_id,
        "email": email,
        "full_name": " ".join(part for part in (data.get("first_name"), data.get("last_name")) if part),
        "phone": phone,
        "role": (existing or {}).get("role", Role.student.value),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    user_repo.upsert(profile)
    return {"status": "synchronized"}

@router.post("/api/auth/logout")
def logout() -> dict[str, str]:
    return {"message": "Logged out; discard the bearer token on the client"}

@router.get("/api/auth/roles/{user_id}")
def role_metadata(user_id: str, _: dict = Depends(require_supabase_role(Role.administrator))) -> dict:
    user = user_repo.get_by_clerk_id(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return {"user_id": user["clerk_id"], "role": user["role"]}

@router.get("/api/users/me")
def get_profile(user: dict = Depends(current_supabase_user)) -> dict:
    return user

@router.put("/api/users/me")
def update_profile(data: dict, user: dict = Depends(current_supabase_user)) -> dict:
    updates = {key: data[key] for key in ("full_name", "phone") if key in data}
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        user_repo.update(user["clerk_id"], updates)
    return {**user, **updates}

def _is_uuid(val: str | None) -> bool:
    if not val:
        return False
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, AttributeError, TypeError):
        return False

@router.post("/api/tickets", status_code=201)
@limiter.limit("15/minute")
def create_ticket(request: Request, data: TicketCreate, user: dict = Depends(current_supabase_user)) -> dict:
    dept_id = data.department_id
    cat_id = data.category_id

    if not _is_uuid(dept_id) or not _is_uuid(cat_id):
        depts = department_repo.get_all()
        dept = None
        if dept_id and not _is_uuid(dept_id):
            dept = next((d for d in depts if d.get("name") == dept_id), None)
        if not dept:
            dept = next((d for d in depts if d.get("name") == "Other"), depts[0] if depts else None)
        if dept:
            dept_id = dept["id"]
            cats = category_repo.get_by_department(dept_id)
            cat = None
            if cat_id and not _is_uuid(cat_id):
                cat = next((c for c in cats if c.get("name") == cat_id), None)
            if not cat:
                cat = next((c for c in cats if c.get("name") == "Other"), cats[0] if cats else None)
            if cat:
                cat_id = cat["id"]

    # Prevent student from creating duplicate tickets for an active issue
    owner_id = user["clerk_id"]
    active_statuses = [
        TicketStatus.submitted.value,
        TicketStatus.assigned.value,
        TicketStatus.in_progress.value,
        TicketStatus.escalated.value,
        TicketStatus.reopened.value,
    ]
    try:
        existing = get_supabase().table("tickets").select("id, title, status").eq("owner_id", owner_id).in_("status", active_statuses).execute().data or []
        clean_new = re.sub(r"[^\w\s]", " ", (data.title or "").lower()).strip()
        clean_new = re.sub(r"\s+", " ", clean_new)
        new_sub = re.split(r"[—–\-\ufffd|:]", data.title or "")[-1].strip().lower()
        new_sub = re.sub(r"[^\w\s]", " ", new_sub).strip()

        for t in existing:
            clean_old = re.sub(r"[^\w\s]", " ", (t.get("title") or "").lower()).strip()
            clean_old = re.sub(r"\s+", " ", clean_old)
            old_sub = re.split(r"[—–\-\ufffd|:]", t.get("title") or "")[-1].strip().lower()
            old_sub = re.sub(r"[^\w\s]", " ", old_sub).strip()

            if clean_new and clean_old:
                if clean_new == clean_old or (len(clean_new) >= 6 and clean_new in clean_old) or (len(clean_old) >= 6 and clean_old in clean_new):
                    raise HTTPException(400, "You already have an active ticket for this issue. Duplicate submissions are not allowed.")
            if new_sub and old_sub and len(new_sub) >= 4 and new_sub == old_sub:
                raise HTTPException(400, "You already have an active ticket for this issue. Duplicate submissions are not allowed.")
    except HTTPException:
        raise
    except Exception:
        pass

    result = ticket_repo.create_with_history(data.title, data.description, cat_id, dept_id, user["clerk_id"], data.confidential)
    if not result:
        raise HTTPException(502, "Ticket could not be created")
    return result

@router.get("/api/tickets")
def list_tickets(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user: dict = Depends(current_supabase_user)) -> list[dict]:
    return ticket_repo.get_all(offset, limit, user.get("role"), user["clerk_id"])

@router.get("/api/tickets/similar")
def similar_tickets(
    q: str = Query("", max_length=150),
    category_id: str | None = Query(None),
    location: str | None = Query(None),
    limit: int = Query(10, ge=1, le=20),
    user: dict = Depends(current_supabase_user)
) -> list[dict]:
    return ticket_repo.get_similar(q, user.get("role"), user["clerk_id"], category_id, location, limit)

@router.post("/api/tickets/{target_id}/merge")
def merge_tickets_endpoint(
    target_id: str,
    data: TicketMergeRequest,
    admin: dict = Depends(require_supabase_role(Role.administrator))
) -> dict:
    if target_id in data.duplicate_ticket_ids:
        raise HTTPException(400, "Cannot merge a ticket into itself")
    
    result = ticket_repo.merge_tickets(
        target_id, 
        data.duplicate_ticket_ids, 
        admin["clerk_id"], 
        data.resolution_note or ""
    )
    if not result:
        raise HTTPException(404, "Target ticket not found or merge failed")
    
    audit_repo.log_action(
        admin["clerk_id"], 
        "merge_tickets", 
        "ticket", 
        target_id, 
        {"duplicates": data.duplicate_ticket_ids, "note": data.resolution_note}
    )
    return result

@router.get("/api/tickets/confidential")
def confidential_tickets(user: dict = Depends(current_supabase_user)) -> list[dict]:
    return ticket_repo.get_confidential(user.get("role"), user["clerk_id"])

@router.get("/api/tickets/confidential/stream")
def confidential_ticket_stream(user: dict = Depends(current_supabase_user)) -> StreamingResponse:
    payload = ticket_repo.get_confidential(user.get("role"), user["clerk_id"])
    return StreamingResponse(iter([f"event: confidential\ndata: {payload}\n\n"]), media_type="text/event-stream")

@router.get("/api/tickets/{ticket_id}")
def get_ticket(ticket_id: str, user: dict = Depends(current_supabase_user)) -> dict:
    ticket = ticket_repo.get_by_id(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
        
    user_role = user.get("role")
    is_owner = ticket["owner_id"] == user["clerk_id"]
    
    if user_role in (Role.student.value, Role.faculty.value) and not is_owner:
        if ticket.get("confidential"):
            raise HTTPException(403, "You cannot access another user's confidential complaint")
    if user_role == Role.staff.value and ticket.get("assigned_to") != user["clerk_id"]:
        raise HTTPException(403, "You can only access assigned complaints")
        
    # Audit log for administrators monitoring complaints they do not own
    if user_role == Role.administrator.value and not is_owner:
        audit_repo.log_action(user["clerk_id"], "read_ticket", "ticket", ticket_id, {"title": ticket["title"]})
        
    history = ticket_repo.get_history(ticket_id)
    media = media_repo.get_by_ticket_id(ticket_id)
    attachments = [m["secure_url"] for m in media if m.get("secure_url")]
    return {**ticket, "history": history, "media": media, "attachments": attachments}

@router.get("/api/tickets/{ticket_id}/media")
def get_ticket_media(ticket_id: str, user: dict = Depends(current_supabase_user)) -> list[dict]:
    ticket = ticket_repo.get_by_id(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
        
    user_role = user.get("role")
    is_owner = ticket["owner_id"] == user["clerk_id"]
    
    if user_role in (Role.student.value, Role.faculty.value) and not is_owner:
        if ticket.get("confidential"):
            raise HTTPException(403, "You cannot access another user's confidential complaint media")
    if user_role == Role.staff.value and ticket.get("assigned_to") != user["clerk_id"]:
        raise HTTPException(403, "You can only access assigned complaints media")
        
    return media_repo.get_by_ticket_id(ticket_id)

@router.post("/api/tickets/{ticket_id}/follow")
def follow_ticket(ticket_id: str, user: dict = Depends(current_supabase_user)) -> dict[str, str]:
    if not ticket_repo.get_by_id(ticket_id):
        raise HTTPException(404, "Ticket not found")
    ticket_repo.add_follower(ticket_id, user["clerk_id"])
    return {"ticket_id": ticket_id, "user_id": user["clerk_id"], "status": "following"}

@router.delete("/api/tickets/{ticket_id}/follow")
def unfollow_ticket(ticket_id: str, user: dict = Depends(current_supabase_user)) -> dict[str, str]:
    ticket_repo.remove_follower(ticket_id, user["clerk_id"])
    return {"ticket_id": ticket_id, "user_id": user["clerk_id"], "status": "unfollowed"}

@router.post("/api/tickets/{ticket_id}/join")
def join_ticket(ticket_id: str, user: dict = Depends(current_supabase_user)) -> dict:
    if not ticket_repo.get_by_id(ticket_id):
        raise HTTPException(404, "Ticket not found")
    ticket_repo.add_supporter(ticket_id, user["clerk_id"])
    count = ticket_repo.get_supporter_count(ticket_id)
    return {"ticket_id": ticket_id, "user_id": user["clerk_id"], "status": "joined", "count": count}

@router.post("/api/tickets/{ticket_id}/appointment")
def propose_appointment(ticket_id: str, data: AppointmentProposal, user: dict = Depends(current_supabase_user)) -> dict:
    if user.get("role") not in (Role.staff.value, Role.administrator.value):
        raise HTTPException(403, "Only staff or administrators can propose appointments")
    if not ticket_repo.get_by_id(ticket_id):
        raise HTTPException(404, "Ticket not found")
    if data.ends_at <= data.starts_at:
        raise HTTPException(400, "Appointment end must be after its start")
    result = appointment_repo.create(ticket_id, user["clerk_id"], data.starts_at, data.ends_at)
    return result[0] if result else {"status": "created"}

@router.put("/api/tickets/{ticket_id}/appointment")
def respond_to_appointment(ticket_id: str, data: AppointmentResponse, user: dict = Depends(current_supabase_user)) -> dict:
    if data.decision not in {"accepted", "rejected"}:
        raise HTTPException(400, "Decision must be accepted or rejected")
    appointment = appointment_repo.get_pending(ticket_id)
    if not appointment:
        raise HTTPException(404, "Pending appointment not found")
    result = appointment_repo.update_decision(appointment[0]["id"], data.decision)
    return result[0] if result else {"status": data.decision}

@router.post("/api/tickets/{ticket_id}/acknowledge")
def acknowledge_ticket(ticket_id: str, data: AcknowledgeRequest, user: dict = Depends(current_supabase_user)) -> dict:
    if user.get("role") not in (Role.staff.value, Role.administrator.value):
        raise HTTPException(403, "Only staff or administrators can acknowledge complaints")
    ticket = ticket_repo.get_by_id(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if user.get("role") == Role.staff and ticket.get("assigned_to") != user["clerk_id"]:
        raise HTTPException(403, "Only the assigned staff member can acknowledge this complaint")
    old_status = ticket.get("status")
    ticket_repo.acknowledge_ticket(ticket_id, data.technician_id, data.name)
    notification_service.notify_status_change(ticket_id, ticket["owner_id"], old_status, TicketStatus.in_progress.value)
    return get_ticket(ticket_id, user)

@router.post("/api/assignments/tickets/{ticket_id}/assign")
def assign_ticket(ticket_id: str, data: AssignmentRequest, admin: dict = Depends(require_supabase_role(Role.administrator))) -> dict:
    ticket = ticket_repo.get_by_id(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket["status"] == TicketStatus.resolved.value:
        raise HTTPException(400, "Cannot assign a resolved complaint")
    if ticket["status"] == TicketStatus.in_progress.value:
        raise HTTPException(400, "Complaint is currently being fixed by a technician. Cannot reassign while in progress.")
        
    result = ticket_repo.assign_ticket(ticket_id, data.technician_id, admin["clerk_id"])
    if not result:
        raise HTTPException(404, "Ticket or technician not found")
        
    notification_service.notify_assignment(ticket_id, data.technician_id, admin["clerk_id"])
    return get_ticket(ticket_id, admin)

@router.put("/api/tickets/{ticket_id}/status")
def update_ticket(ticket_id: str, data: TicketUpdate, user: dict = Depends(current_supabase_user)) -> dict:
    ticket = ticket_repo.get_by_id(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if user.get("role") == Role.staff.value and ticket.get("assigned_to") != user["clerk_id"]:
        raise HTTPException(403, "Only the assigned staff member can update this complaint")
    if user.get("role") not in (Role.staff.value, Role.administrator.value):
        raise HTTPException(403, "Only staff or administrators can update complaint status")
        
    current_status = ticket["status"]
    new_status = data.status.value
    
    if current_status == TicketStatus.resolved.value:
        raise HTTPException(400, "Cannot update a resolved complaint directly. Reopen it first.")
    
    if current_status == TicketStatus.submitted.value and new_status != TicketStatus.assigned.value:
        raise HTTPException(400, "Submitted complaints must be assigned first.")
        
    ticket_repo.update_status_with_history(ticket_id, new_status, data.remarks, user["clerk_id"])
    notification_service.notify_status_change(ticket_id, ticket["owner_id"], current_status, new_status)
    return get_ticket(ticket_id, user)

@router.post("/api/tickets/{ticket_id}/resolve")
def resolve_ticket(ticket_id: str, data: TicketAction, user: dict = Depends(current_supabase_user)) -> dict:
    if user.get("role") not in (Role.staff.value, Role.administrator.value):
        raise HTTPException(403, "Only staff or administrators can resolve complaints")
    ticket = ticket_repo.get_by_id(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket["status"] == TicketStatus.submitted.value:
        raise HTTPException(400, "Cannot resolve an unassigned complaint")
    if ticket["status"] == TicketStatus.resolved.value:
        raise HTTPException(400, "Complaint is already resolved")
    if user.get("role") == Role.staff.value and ticket.get("assigned_to") != user["clerk_id"]:
        raise HTTPException(403, "Only the assigned staff member can resolve this complaint")
        
    ticket_repo.update_status_with_history(ticket_id, TicketStatus.resolved.value, data.remarks or "Resolved by technician", user["clerk_id"], data.attachments)
    notification_service.notify_resolution(ticket_id, ticket["owner_id"])
    return get_ticket(ticket_id, user)

@router.post("/api/tickets/{ticket_id}/reopen")
def reopen_ticket(ticket_id: str, data: TicketAction, user: dict = Depends(current_supabase_user)) -> dict:
    ticket = ticket_repo.get_by_id(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket["owner_id"] != user["clerk_id"] and user.get("role") != Role.administrator.value:
        raise HTTPException(403, "Only the owner or an administrator can reopen a complaint")
    if ticket["status"] != TicketStatus.resolved.value:
        raise HTTPException(400, "Only resolved complaints can be reopened")
        
    ticket_repo.update_status_with_history(ticket_id, TicketStatus.reopened.value, data.remarks, user["clerk_id"])
    notification_service.notify_status_change(ticket_id, ticket["owner_id"], TicketStatus.resolved.value, TicketStatus.reopened.value)
    return get_ticket(ticket_id, user)

@router.post("/api/tickets/{ticket_id}/escalate")
def escalate_ticket(ticket_id: str, data: TicketAction, user: dict = Depends(current_supabase_user)) -> dict:
    if user.get("role") not in (Role.staff.value, Role.administrator.value):
        raise HTTPException(403, "Only staff or administrators can escalate complaints")
    ticket = ticket_repo.get_by_id(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket["status"] in (TicketStatus.submitted.value, TicketStatus.resolved.value, TicketStatus.escalated.value):
        raise HTTPException(400, f"Cannot escalate a complaint that is {ticket['status']}")
        
    ticket_repo.update_status_with_history(ticket_id, TicketStatus.escalated.value, data.remarks, user["clerk_id"])
    notification_service.notify_status_change(ticket_id, ticket["owner_id"], ticket["status"], TicketStatus.escalated.value)
    return get_ticket(ticket_id, user)

@router.post("/api/tickets/{ticket_id}/feedback", status_code=201)
def submit_feedback(ticket_id: str, data: FeedbackCreate, user: dict = Depends(current_supabase_user)) -> dict:
    ticket = ticket_repo.get_by_id(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
        
    status_lower = str(ticket.get("status", "")).lower().strip()
    if status_lower not in (TicketStatus.resolved.value, "fixed", "done"):
        raise HTTPException(400, "Feedback can only be provided after the issue has been resolved")

    is_owner = ticket.get("owner_id") == user["clerk_id"]
    is_supporter = False
    if not is_owner and not ticket.get("confidential"):
        try:
            sup_res = get_supabase().table("ticket_supporters").select("user_id").eq("ticket_id", ticket_id).eq("user_id", user["clerk_id"]).maybe_single().execute()
            is_supporter = bool(sup_res and sup_res.data)
        except Exception:
            is_supporter = False

    is_admin = user.get("role") == Role.administrator.value
    if not is_owner and not is_supporter and not is_admin:
        raise HTTPException(403, "Only the reporter or affected students can provide feedback")

    result = feedback_repo.submit(ticket_id, user["clerk_id"], data.rating, data.comment)
    if not result:
        raise HTTPException(502, "Feedback could not be saved")
    return result

@router.post("/api/files/upload")
@limiter.limit("10/minute")
def upload_file(request: Request, file: Annotated[UploadFile, File(...)], ticket_id: Annotated[str | None, Form()] = None, user: dict = Depends(current_supabase_user)) -> dict:
    allowed_types = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
    if file.content_type not in allowed_types:
        raise HTTPException(415, "Only JPEG, PNG, WebP, and PDF files are allowed")
    content = file.file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "File size must not exceed 10 MB")
    
    # Validate magic numbers/signatures to prevent MIME spoofing and malicious files
    is_valid_magic = (
        content.startswith(b"\xff\xd8\xff") or  # JPEG
        content.startswith(b"\x89PNG\r\n\x1a\n") or  # PNG
        (content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP") or  # WebP
        content.startswith(b"%PDF")  # PDF
    )
    if not is_valid_magic:
        raise HTTPException(400, "File content signature does not match allowed file types (JPEG, PNG, WebP, PDF)")
    
    if ticket_id:
        ticket = ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise HTTPException(404, "Ticket not found")
        if user.get("role") in (Role.student.value, Role.faculty.value) and ticket["owner_id"] != user["clerk_id"]:
            raise HTTPException(403, "You cannot attach media to another user's complaint")
        if user.get("role") == Role.staff.value and ticket.get("assigned_to") != user["clerk_id"]:
            raise HTTPException(403, "You can only attach media to assigned complaints")
    try:
        media = upload_media(content, file.filename or "upload", user["clerk_id"])
    except Exception as exc:
        raise HTTPException(502, "Cloudinary upload failed") from exc
    
    record = media_repo.create({"ticket_id": ticket_id, "uploaded_by": user["clerk_id"], **media})
    return record[0] if record else media

@router.post("/api/files/upload/signature")
def upload_signature(filename: str, content_type: str, user: dict = Depends(current_supabase_user)) -> dict[str, str | int]:
    if content_type not in {"image/jpeg", "image/png", "image/webp", "application/pdf"}:
        raise HTTPException(415, "Only JPEG, PNG, WebP, and PDF files are allowed")
    return signed_upload_parameters(user["clerk_id"], filename)

@router.delete("/api/files/{media_id}")
def delete_file(media_id: str, user: dict = Depends(current_supabase_user)) -> dict[str, str]:
    media = media_repo.get_by_id(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    if media.get("uploaded_by") != user["clerk_id"] and user.get("role") != Role.administrator.value:
        raise HTTPException(403, "You cannot delete this media")
    try:
        delete_media(media["public_id"], media.get("resource_type"))
    except Exception as exc:
        raise HTTPException(502, "Cloudinary deletion failed") from exc
    media_repo.delete(media_id)
    return {"id": media_id, "status": "deleted"}

@router.get("/api/staff/technicians")
def technicians(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), _: dict = Depends(current_supabase_user)) -> list[dict]:
    return user_repo.get_technicians(offset, limit)

@router.put("/api/staff/me/status")
def update_my_duty_status(data: dict, user: dict = Depends(require_supabase_role(Role.staff, Role.administrator))) -> dict:
    status = data.get("status", "On Duty")
    if status not in ("On Duty", "Off Duty"):
        raise HTTPException(400, "Status must be 'On Duty' or 'Off Duty'")
    audit_repo.log_action(user["clerk_id"], "update_duty_status", "user", user["clerk_id"], {"status": status})
    return user_repo.update_technician_status(user["clerk_id"], status)

@router.put("/api/staff/technicians/{tech_id}/status")
def update_technician_duty_status(tech_id: str, data: dict, user: dict = Depends(current_supabase_user)) -> dict:
    user_role = user.get("role")
    if user_role != Role.administrator.value and user.get("clerk_id") != tech_id:
        raise HTTPException(403, "Cannot change duty status of another technician")
    status = data.get("status", "On Duty")
    if status not in ("On Duty", "Off Duty"):
        raise HTTPException(400, "Status must be 'On Duty' or 'Off Duty'")
    audit_repo.log_action(user["clerk_id"], "update_duty_status", "user", tech_id, {"status": status})
    return user_repo.update_technician_status(tech_id, status)

@router.get("/api/messages/me/{user_id}")
def my_messages(user_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user: dict = Depends(current_supabase_user)) -> list[dict]:
    if user_id != user["clerk_id"] and user.get("role") != Role.administrator.value:
        raise HTTPException(403, "Cannot access another user's messages")
    return message_repo.get_user_messages(user_id, offset, limit)

def is_lost_and_found_ticket(ticket: dict | None) -> bool:
    if not ticket:
        return False
    title = str(ticket.get("title") or "").lower()
    desc = str(ticket.get("description") or "").lower()
    cat = str(ticket.get("category") or ticket.get("category_name") or "").lower()
    sub = str(ticket.get("sub_category") or ticket.get("subCategory") or "").lower()
    haystack = f"{title} {cat} {sub} {desc[:150]}"
    return (
        "lost & found" in haystack
        or "lost and found" in haystack
        or "[lost]" in haystack
        or "[found]" in haystack
        or "lost/found" in haystack
        or "lost item" in haystack
        or "found item" in haystack
    )

@router.get("/api/messages/thread/{thread_id}")
def get_thread(thread_id: str, user: dict = Depends(current_supabase_user)) -> list[dict]:
    user_id = user["clerk_id"]
    is_admin = user.get("role") == Role.administrator.value
    ticket = None
    try:
        res = get_supabase().table("tickets").select("id, owner_id, assigned_to, title, description").eq("id", thread_id).maybe_single().execute()
        ticket = res.data if res else None
    except Exception:
        ticket = None

    if ticket:
        is_owner = ticket.get("owner_id") == user_id
        is_assigned = ticket.get("assigned_to") == user_id
        is_lf = is_lost_and_found_ticket(ticket)
        # Lost & Found chats are open for all campus members to view and claim
        if not (is_admin or is_owner or is_assigned or is_lf):
            raise HTTPException(403, "Access denied to ticket messages")
        return message_repo.get_thread(thread_id)
    else:
        thread_messages = message_repo.get_thread(thread_id)
        if thread_messages:
            if not is_admin and not any(m["sender_id"] == user_id or m.get("recipient_id") == user_id for m in thread_messages):
                raise HTTPException(403, "Access denied to this conversation")
        return thread_messages

@router.get("/api/messages/admin")
def admin_messages(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), admin: dict = Depends(require_supabase_role(Role.administrator))) -> list[dict]:
    return message_repo.get_admin_messages(offset, limit)

@router.put("/api/messages/{message_id}/read")
def mark_message_read(message_id: str, user: dict = Depends(current_supabase_user)) -> dict:
    msg = message_repo.get_by_id(message_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    # SECURITY FIX: Only the intended recipient or an administrator can mark the message as read
    if msg.get("recipient_id") and msg.get("recipient_id") != user["clerk_id"] and user.get("role") != Role.administrator.value:
        raise HTTPException(403, "Cannot mark another user's message as read")
    message_repo.mark_read(message_id)
    return {"id": message_id, "status": "read"}

@router.put("/api/messages/thread/{thread_id}/read")
def mark_thread_messages_read(thread_id: str, user: dict = Depends(current_supabase_user)) -> dict:
    user_id = user["clerk_id"]
    is_admin = user.get("role") == Role.administrator.value
    res = message_repo.mark_thread_read(thread_id, reader_id=user_id, is_admin=is_admin)
    return {"thread_id": thread_id, "status": "read", "updated": len(res or [])}

@router.post("/api/messages", status_code=201)
@limiter.limit("30/minute")
def send_message(request: Request, data: MessageCreate, user: dict = Depends(current_supabase_user)) -> dict:
    user_id = user["clerk_id"]
    is_admin = user.get("role") == Role.administrator.value

    ticket = None
    if data.thread_id:
        try:
            res = get_supabase().table("tickets").select("id, owner_id, assigned_to, title, description").eq("id", data.thread_id).maybe_single().execute()
            ticket = res.data if res else None
        except Exception:
            ticket = None

        if ticket:
            is_owner = ticket.get("owner_id") == user_id
            is_assigned = ticket.get("assigned_to") == user_id
            is_lf = is_lost_and_found_ticket(ticket)
            # Lost & Found chats are open for all campus members to message and claim
            if not (is_admin or is_owner or is_assigned or is_lf):
                raise HTTPException(403, "You cannot send messages to this ticket thread")
        else:
            thread_messages = message_repo.get_thread(data.thread_id)
            if thread_messages:
                if not is_admin and not any(m["sender_id"] == user_id or m.get("recipient_id") == user_id for m in thread_messages):
                    raise HTTPException(403, "You cannot reply to a conversation you are not a part of")
            elif not data.recipient_id:
                raise HTTPException(404, "Thread not found")

    payload = {"sender_id": user_id, **data.model_dump(exclude_none=True)}
    if ticket and not payload.get("recipient_id"):
        owner_id = ticket.get("owner_id")
        if owner_id and owner_id != user_id:
            payload["recipient_id"] = owner_id
    try:
        result = message_repo.create(payload)
    except Exception as exc:
        err_msg = str(exc)
        if "thread_id" in err_msg:
            raise HTTPException(500, "Missing 'thread_id' column in Supabase: please execute lines 335-338 of schema.sql in your Supabase SQL editor.")
        raise HTTPException(502, f"Message could not be saved: {err_msg}")

    if not result:
        raise HTTPException(502, "Message could not be saved")
    msg = result[0]
    msg["sender_name"] = user.get("full_name") or user.get("email", "").split("@")[0]
    msg["sender_role"] = user.get("role")
    return msg

@router.get("/api/notices")
def notices(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), _: dict = Depends(current_supabase_user)) -> list[dict]:
    return notice_repo.get_active(offset, limit)

@router.post("/api/notices", status_code=201)
def create_notice(data: NoticeCreate, admin: dict = Depends(require_supabase_role(Role.administrator))) -> dict:
    result = notice_repo.create({**data.model_dump(), "created_by": admin["clerk_id"]})
    if not result:
        raise HTTPException(502, "Notice could not be saved")
    return result[0]

@router.get("/api/settings")
def get_settings(_: dict = Depends(current_supabase_user)) -> dict[str, object]:
    default = {"application": "CampusCare", "version": "1.0.0", "supported_roles": [role.value for role in Role]}
    db_settings = settings_repo.get()
    return {**default, **db_settings}

@router.put("/api/settings")
def update_settings(data: SettingsUpdate, admin: dict = Depends(require_supabase_role(Role.administrator))) -> dict[str, object]:
    audit_repo.log_action(admin["clerk_id"], "update_settings", "settings", "global", {})
    return settings_repo.update(data.config)

@router.get("/api/audit-log")
def audit_log(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), _: dict = Depends(require_supabase_role(Role.administrator))) -> list[dict]:
    return audit_repo.get_logs(offset, limit)

@router.get("/api/diagnostics/services")
def diagnostics_services() -> dict[str, object]:
    return {"services": ["auth", "users", "files", "tickets", "assignments", "staff", "messages", "notices", "settings", "audit"]}

@router.get("/api/diagnostics/events")
def diagnostics_events() -> list[dict]:
    return []

@router.get("/api/tickets/stream")
def ticket_stream() -> StreamingResponse:
    return StreamingResponse(iter(["event: ready\ndata: {}\n\n"]), media_type="text/event-stream")

@router.get("/api/departments")
def list_departments(_: dict = Depends(current_supabase_user)) -> list[dict]:
    return department_repo.get_all()

@router.get("/api/departments/{department_id}/categories")
def list_categories(department_id: str, _: dict = Depends(current_supabase_user)) -> list[dict]:
    return category_repo.get_by_department(department_id)

@router.get("/api/admin/users")
def list_all_users(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), _: dict = Depends(require_supabase_role(Role.administrator))) -> list[dict]:
    return user_repo.get_all(offset, limit)

@router.put("/api/admin/users/{user_id}/role")
def update_user_role(user_id: str, data: RoleUpdate, admin: dict = Depends(require_supabase_role(Role.administrator))) -> dict:
    if admin["clerk_id"] == user_id:
        raise HTTPException(400, "Cannot change your own role")
    user = user_repo.get_by_clerk_id(user_id)
    if not user:
        raise HTTPException(404, "User not found")
        
    audit_repo.log_action(admin["clerk_id"], "update_role", "user", user_id, {"old_role": user["role"], "new_role": data.role.value})
    user_repo.update_role(user_id, data.role.value)
    
    return {**user, "role": data.role.value}

@router.post("/api/admin/users", status_code=201)
def create_user_by_admin(data: AdminUserCreate, admin: dict = Depends(require_supabase_role(Role.administrator))) -> dict:
    email = str(data.email).lower().strip()
    existing = get_supabase().table("users").select("*").eq("email", email).maybe_single().execute()
    if existing and existing.data:
        clerk_id = existing.data["clerk_id"]
        user_repo.update(clerk_id, {
            "full_name": data.name,
            "phone": data.phone,
            "role": data.role.value,
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
        audit_repo.log_action(admin["clerk_id"], "update_role", "user", clerk_id, {"role": data.role.value})
        return user_repo.get_by_clerk_id(clerk_id)
    else:
        clerk_id = None
        secret = settings.clerk_secret_key or settings.clerk_webhook_secret
        if secret and secret.startswith("sk_"):
            try:
                r = httpx.get(
                    f"https://api.clerk.com/v1/users?email_address={email}",
                    headers={"Authorization": f"Bearer {secret}", "User-Agent": "CampusCareBackend/1.0"},
                    timeout=5.0
                )
                if r.status_code == 200 and r.json():
                    clerk_id = r.json()[0].get("id")
                else:
                    parts = str(data.name).split()
                    first_name = parts[0] if parts else "Staff"
                    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
                    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
                    init_pw = "CC@" + "".join(secrets.choice(alphabet) for _ in range(12)) + "!"
                    cr = httpx.post(
                        "https://api.clerk.com/v1/users",
                        headers={
                            "Authorization": f"Bearer {secret}",
                            "User-Agent": "CampusCareBackend/1.0",
                            "Content-Type": "application/json"
                        },
                        json={
                            "email_address": [email],
                            "first_name": first_name,
                            "last_name": last_name,
                            "password": init_pw,
                            "skip_password_checks": True,
                            "skip_legal_checks": True,
                            "bypass_client_trust": True
                        },
                        timeout=6.0
                    )
                    if cr.status_code in (200, 201):
                        clerk_id = cr.json().get("id")
            except Exception:
                pass

        new_id = clerk_id or f"staff_{uuid.uuid4().hex[:16]}"
        profile = {
            "clerk_id": new_id,
            "email": email,
            "full_name": data.name,
            "phone": data.phone,
            "role": data.role.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        res = user_repo.create(profile)
        audit_repo.log_action(admin["clerk_id"], "create_user", "user", new_id, {"role": data.role.value})
        return res[0] if isinstance(res, list) and res else profile

@router.delete("/api/admin/users/{user_id}")
def delete_user_by_admin(user_id: str, admin: dict = Depends(require_supabase_role(Role.administrator))) -> dict:
    if admin["clerk_id"] == user_id:
        raise HTTPException(400, "Cannot delete your own account")
    user_repo.delete(user_id)
    audit_repo.log_action(admin["clerk_id"], "delete_user", "user", user_id, {})
    return {"user_id": user_id, "status": "deleted"}

@router.post("/api/admin/users/{user_id}/reset-password")
@limiter.limit("10/minute")
def reset_user_password_by_admin(request: Request, user_id: str, admin: dict = Depends(require_supabase_role(Role.administrator))) -> dict:
    target_user = user_repo.get_by_clerk_id(user_id)
    if not target_user:
        res_email = get_supabase().table("users").select("*").eq("email", str(user_id).lower().strip()).maybe_single().execute()
        if res_email and res_email.data:
            target_user = res_email.data

    if not target_user:
        raise HTTPException(404, "User not found")

    email = str(target_user.get("email") or "").strip().lower()
    clerk_id = target_user.get("clerk_id")

    secret = settings.clerk_secret_key or settings.clerk_webhook_secret
    if not secret or not secret.startswith("sk_"):
        raise HTTPException(500, "Clerk secret key is not configured on server")

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    temp_password = "CC@" + "".join(secrets.choice(alphabet) for _ in range(12)) + "!"
    sign_in_url = None

    # 1. Resolve or create user in Clerk
    if not clerk_id or clerk_id.startswith("staff_") or clerk_id.startswith("local_"):
        try:
            r = httpx.get(
                f"https://api.clerk.com/v1/users?email_address={email}",
                headers={"Authorization": f"Bearer {secret}", "User-Agent": "CampusCareBackend/1.0"},
                timeout=5.0
            )
            if r.status_code == 200 and r.json():
                clerk_id = r.json()[0]["id"]
            else:
                # User does not exist in Clerk yet -> create them in Clerk now!
                parts = str(target_user.get("full_name") or target_user.get("name") or "Staff").split()
                first_name = parts[0] if parts else "Staff"
                last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
                cr = httpx.post(
                    "https://api.clerk.com/v1/users",
                    headers={
                        "Authorization": f"Bearer {secret}",
                        "User-Agent": "CampusCareBackend/1.0",
                        "Content-Type": "application/json"
                    },
                    json={
                        "email_address": [email],
                        "first_name": first_name,
                        "last_name": last_name,
                        "password": temp_password,
                        "skip_password_checks": True,
                        "skip_legal_checks": True,
                        "bypass_client_trust": True
                    },
                    timeout=6.0
                )
                if cr.status_code in (200, 201):
                    clerk_id = cr.json().get("id")

            if clerk_id:
                get_supabase().table("users").update({"clerk_id": clerk_id}).eq("email", email).execute()
                target_user["clerk_id"] = clerk_id
        except Exception:
            pass

    # 2. If user already exists in Clerk, update their password and trust
    if clerk_id and not clerk_id.startswith("staff_"):
        try:
            httpx.patch(
                f"https://api.clerk.com/v1/users/{clerk_id}",
                headers={
                    "Authorization": f"Bearer {secret}",
                    "User-Agent": "CampusCareBackend/1.0",
                    "Content-Type": "application/json"
                },
                json={
                    "password": temp_password,
                    "skip_password_checks": True,
                    "bypass_client_trust": True,
                    "sign_out_of_other_sessions": False
                },
                timeout=6.0
            )
        except Exception:
            pass

        # 3. Generate direct 1-click login URL
        try:
            tok_res = httpx.post(
                "https://api.clerk.com/v1/sign_in_tokens",
                headers={
                    "Authorization": f"Bearer {secret}",
                    "User-Agent": "CampusCareBackend/1.0",
                    "Content-Type": "application/json"
                },
                json={"user_id": clerk_id},
                timeout=5.0
            )
            if tok_res.status_code in (200, 201):
                sign_in_url = tok_res.json().get("url")
        except Exception:
            pass

    audit_repo.log_action(admin["clerk_id"], "reset_password", "user", clerk_id or email, {"email": email})

    return {
        "success": True,
        "email": email,
        "name": target_user.get("full_name") or target_user.get("name") or "Staff member",
        "temp_password": temp_password,
        "tempPassword": temp_password,
        "sign_in_url": sign_in_url,
        "signInUrl": sign_in_url,
        "message": f"Temporary password set to: {temp_password}"
    }

@router.put("/api/notices/{notice_id}/end")
def end_notice(notice_id: str, admin: dict = Depends(require_supabase_role(Role.administrator))) -> dict:
    notice = notice_repo.get_by_id(notice_id)
    if not notice:
        raise HTTPException(404, "Notice not found")
        
    audit_repo.log_action(admin["clerk_id"], "end_notice", "notices", notice_id, {})
    result = notice_repo.end_notice(notice_id)
    return result[0] if result else notice

@router.get("/api/audit-log/export")
def export_audit_logs(admin: dict = Depends(require_supabase_role(Role.administrator))):
    audit_repo.log_action(admin["clerk_id"], "export_logs", "audit_logs", "all", {})
    logs = audit_repo.stream_all_logs()
    
    def generate():
        for log in logs:
            yield json.dumps(log) + "\n"
            
    return StreamingResponse(generate(), media_type="application/x-ndjson", headers={"Content-Disposition": "attachment; filename=audit_export.ndjson"})

@router.delete("/api/audit-log")
def apply_retention_policy(older_than_days: int = Query(90, ge=1), admin: dict = Depends(require_supabase_role(Role.administrator))) -> dict:
    audit_repo.log_action(admin["clerk_id"], "apply_retention", "audit_logs", "bulk", {"days": older_than_days})
    result = audit_repo.delete_older_than(older_than_days)
    return {"message": f"Deleted audit logs older than {older_than_days} days", "deleted_count": len(result)}

@router.post("/api/webhooks/cloudinary")
async def cloudinary_webhook(request: Request) -> dict[str, str]:
    # Cloudinary webhook signature verification
    timestamp = request.headers.get("x-cld-timestamp")
    signature = request.headers.get("x-cld-signature")
    if not timestamp or not signature:
        raise HTTPException(status_code=400, detail="Missing Cloudinary webhook headers")
        
    body = await request.body()
    # verify signature: SHA-1 of body + timestamp + api_secret
    payload = body.decode('utf-8') + timestamp + settings.cloudinary_api_secret
    expected_sig = hashlib.sha1(payload.encode('utf-8')).hexdigest()
    
    if not hmac.compare_digest(expected_sig, signature):
        raise HTTPException(status_code=400, detail="Invalid Cloudinary webhook signature")
        
    data = await request.json()
    notification_type = data.get("notification_type")
    
    # Handle moderation rejection (e.g. offensive content detected)
    if notification_type == "moderation":
        moderation_status = data.get("moderation_status")
        public_id = data.get("public_id")
        if moderation_status == "rejected" and public_id:
            # Delete it from our DB (it's already rejected in Cloudinary)
            media_repo.delete(public_id)
            audit_repo.log_action("system", "cloudinary_moderation_reject", "media", public_id, {})
            
    return {"status": "received"}
