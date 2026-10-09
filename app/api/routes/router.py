
from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from svix.webhooks import Webhook, WebhookVerificationError
import uuid
from datetime import datetime, timezone
from app.core.config import settings
from app.core.cloudinary import delete_media, signed_upload_parameters, upload_media
from app.schemas import *
from app.api.deps import current_supabase_user, require_supabase_role
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
    from app.api.deps import resolve_or_link_user
    user_id = claims["sub"]
    email_hint = email or claims.get("email")
    return resolve_or_link_user(user_id, email_hint=email_hint, name_hint=name)

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

    email = next((item.get("email_address", "") for item in data.get("email_addresses", []) if item.get("id") == data.get("primary_email_address_id")), "")
    phone = next((item.get("phone_number") for item in data.get("phone_numbers", []) if item.get("id") == data.get("primary_phone_number_id")), None)
    
    existing = user_repo.get_by_clerk_id(clerk_id)
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

@router.post("/api/tickets", status_code=201)
def create_ticket(data: TicketCreate, user: dict = Depends(current_supabase_user)) -> dict:
    result = ticket_repo.create_with_history(data.title, data.description, data.category_id, data.department_id, user["clerk_id"], data.confidential)
    if not result:
        raise HTTPException(502, "Ticket could not be created")
    return result

@router.get("/api/tickets")
def list_tickets(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user: dict = Depends(current_supabase_user)) -> list[dict]:
    return ticket_repo.get_all(offset, limit, user.get("role"), user["clerk_id"])

@router.get("/api/tickets/similar")
def similar_tickets(q: str = Query(min_length=2, max_length=100), user: dict = Depends(current_supabase_user)) -> list[dict]:
    return ticket_repo.get_similar(q, user.get("role"), user["clerk_id"])

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
        raise HTTPException(403, "You cannot access another user's complaint")
    if user_role == Role.staff.value and ticket.get("assigned_to") != user["clerk_id"]:
        raise HTTPException(403, "You can only access assigned complaints")
        
    # Audit log for administrators monitoring complaints they do not own
    if user_role == Role.administrator.value and not is_owner:
        audit_repo.log_action(user["clerk_id"], "read_ticket", "ticket", ticket_id, {"title": ticket["title"]})
        
    history = ticket_repo.get_history(ticket_id)
    return {**ticket, "history": history}

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
def join_ticket(ticket_id: str, user: dict = Depends(current_supabase_user)) -> dict[str, str]:
    if not ticket_repo.get_by_id(ticket_id):
        raise HTTPException(404, "Ticket not found")
    ticket_repo.add_supporter(ticket_id, user["clerk_id"])
    return {"ticket_id": ticket_id, "user_id": user["clerk_id"], "status": "joined"}

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
    if ticket["owner_id"] != user["clerk_id"] or ticket["status"] != TicketStatus.resolved.value:
        raise HTTPException(400, "Only the owner can provide feedback after resolution")
    result = feedback_repo.submit(ticket_id, user["clerk_id"], data.rating, data.comment)
    if not result:
        raise HTTPException(502, "Feedback could not be saved")
    return result

@router.post("/api/files/upload")
def upload_file(request: Request, file: Annotated[UploadFile, File(...)], ticket_id: Annotated[str | None, Form()] = None, user: dict = Depends(current_supabase_user)) -> dict:
    allowed_types = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
    if file.content_type not in allowed_types:
        raise HTTPException(415, "Only JPEG, PNG, WebP, and PDF files are allowed")
    content = file.file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "File size must not exceed 10 MB")
    
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

@router.get("/api/messages/me/{user_id}")
def my_messages(user_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user: dict = Depends(current_supabase_user)) -> list[dict]:
    if user_id != user["clerk_id"] and user.get("role") != Role.administrator.value:
        raise HTTPException(403, "Cannot access another user's messages")
    return message_repo.get_user_messages(user_id, offset, limit)

@router.get("/api/messages/thread/{thread_id}")
def get_thread(thread_id: str, user: dict = Depends(current_supabase_user)) -> list[dict]:
    user_id = user["clerk_id"]
    is_admin = user.get("role") == Role.administrator.value
    ticket = None
    try:
        ticket = ticket_repo.get_by_id(thread_id)
    except Exception:
        ticket = None

    if ticket:
        is_owner = ticket.get("owner_id") == user_id
        is_assigned = ticket.get("assigned_to") == user_id
        is_staff = user.get("role") in (Role.staff.value, Role.administrator.value)
        if not (is_admin or is_owner or is_assigned or is_staff):
            raise HTTPException(403, "Access denied to ticket messages")
    return message_repo.get_thread(thread_id)

@router.get("/api/messages/admin")
def admin_messages(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), admin: dict = Depends(require_supabase_role(Role.administrator))) -> list[dict]:
    return message_repo.get_admin_messages(offset, limit)

@router.put("/api/messages/{message_id}/read")
def mark_message_read(message_id: str, _: dict = Depends(current_supabase_user)) -> dict:
    message_repo.mark_read(message_id)
    return {"id": message_id, "status": "read"}

@router.post("/api/messages", status_code=201)
def send_message(data: MessageCreate, user: dict = Depends(current_supabase_user)) -> dict:
    user_id = user["clerk_id"]
    is_admin = user.get("role") == Role.administrator.value

    if data.thread_id:
        ticket = None
        try:
            ticket = ticket_repo.get_by_id(data.thread_id)
        except Exception:
            ticket = None

        if ticket:
            is_owner = ticket.get("owner_id") == user_id
            is_assigned = ticket.get("assigned_to") == user_id
            is_staff = user.get("role") in (Role.staff.value, Role.administrator.value)
            if not (is_admin or is_owner or is_assigned or is_staff):
                raise HTTPException(403, "You cannot reply to this ticket thread")
        else:
            thread_messages = message_repo.get_thread(data.thread_id)
            if thread_messages:
                if not is_admin and not any(m["sender_id"] == user_id or m.get("recipient_id") == user_id for m in thread_messages):
                    raise HTTPException(403, "You cannot reply to a conversation you are not a part of")
            elif not data.recipient_id:
                raise HTTPException(404, "Thread not found")

    payload = {"sender_id": user_id, **data.model_dump(exclude_none=True)}
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
    import httpx
    from app.core.supabase import get_supabase
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
                    headers={"Authorization": f"Bearer {secret}"},
                    timeout=5.0
                )
                if r.status_code == 200 and r.json():
                    clerk_id = r.json()[0].get("id")
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

@router.put("/api/notices/{notice_id}/end")
def end_notice(notice_id: str, admin: dict = Depends(require_supabase_role(Role.administrator))) -> dict:
    notice = notice_repo.get_by_id(notice_id)
    if not notice:
        raise HTTPException(404, "Notice not found")
        
    audit_repo.log_action(admin["clerk_id"], "end_notice", "notices", notice_id, {})
    result = notice_repo.end_notice(notice_id)
    return result[0] if result else notice

import json

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

import hashlib
import time

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
    
    if expected_sig != signature:
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
