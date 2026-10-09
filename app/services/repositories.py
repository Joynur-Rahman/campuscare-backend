
from datetime import datetime, timezone
from app.core.supabase import get_supabase
from app.schemas import Role, TicketStatus

class UserRepository:
    def get_by_clerk_id(self, clerk_id: str):
        res = get_supabase().table("users").select("*").eq("clerk_id", clerk_id).maybe_single().execute()
        return res.data if res else None

    def create(self, profile_data: dict):
        return get_supabase().table("users").insert(profile_data).execute().data

    def update(self, clerk_id: str, updates: dict):
        return get_supabase().table("users").update(updates).eq("clerk_id", clerk_id).execute().data

    def upsert(self, profile_data: dict):
        return get_supabase().table("users").upsert(profile_data, on_conflict="clerk_id").execute().data

    def delete(self, clerk_id: str):
        return get_supabase().table("users").delete().eq("clerk_id", clerk_id).execute().data

    def get_admin_emails(self):
        users = get_supabase().table("users").select("email").eq("role", Role.administrator.value).execute().data or []
        return [u["email"] for u in users if u.get("email")]

    def get_technicians(self, offset: int, limit: int):
        return get_supabase().table("users").select("clerk_id, email, full_name, phone, role").eq("role", Role.staff.value).range(offset, offset + limit - 1).execute().data or []

    def get_all(self, offset: int = 0, limit: int = 50):
        return get_supabase().table("users").select("clerk_id, email, full_name, phone, role, created_at, updated_at").order("created_at", desc=True).range(offset, offset + limit - 1).execute().data or []

    def update_role(self, clerk_id: str, role: str):
        return self.update(clerk_id, {"role": role})

class TicketRepository:
    def create_with_history(self, title, description, category_id, department_id, owner_id, confidential):
        result = get_supabase().rpc("create_ticket_with_history", {
            "p_title": title, "p_description": description, "p_category_id": category_id, 
            "p_department_id": department_id, "p_owner_id": owner_id, "p_confidential": confidential
        }).execute().data
        return result[0] if isinstance(result, list) and result else result

    def get_all(self, offset, limit, user_role, user_id):
        query = get_supabase().table("tickets").select("*")
        if user_role in (Role.student.value, Role.faculty.value):
            query = query.eq("owner_id", user_id)
        elif user_role == Role.staff.value:
            query = query.eq("assigned_to", user_id)
        return query.order("created_at", desc=True).range(offset, offset + limit - 1).execute().data or []

    def get_similar(self, q, user_role, user_id):
        query = get_supabase().table("tickets").select("*").in_("status", [TicketStatus.submitted.value, TicketStatus.assigned.value, TicketStatus.in_progress.value]).ilike("title", f"%{q}%")
        if user_role in (Role.student.value, Role.faculty.value):
            query = query.eq("owner_id", user_id)
        return query.order("created_at", desc=True).limit(20).execute().data or []

    def get_confidential(self, user_role, user_id):
        query = get_supabase().table("tickets").select("*").eq("confidential", True)
        if user_role in (Role.student.value, Role.faculty.value):
            query = query.eq("owner_id", user_id)
        elif user_role == Role.staff.value:
            query = query.eq("assigned_to", user_id)
        elif user_role != Role.administrator.value:
            return []
        return query.order("created_at", desc=True).execute().data or []

    def get_by_id(self, ticket_id):
        res = get_supabase().table("tickets").select("*").eq("id", ticket_id).maybe_single().execute()
        return res.data if res else None

    def get_history(self, ticket_id):
        return get_supabase().table("ticket_history").select("*").eq("ticket_id", ticket_id).order("created_at").execute().data or []

    def update_status_with_history(self, ticket_id, status, remarks, actor_id, attachments=None):
        payload = {
            "p_ticket_id": ticket_id,
            "p_status": status,
            "p_remarks": remarks or "",
            "p_actor_id": actor_id,
            "p_attachments": attachments or []
        }
        return get_supabase().rpc("update_ticket_with_history", payload).execute().data

    def assign_ticket(self, ticket_id, assigned_to, actor_id):
        return get_supabase().rpc("assign_ticket_with_history", {
            "p_ticket_id": ticket_id, "p_assigned_to": assigned_to, "p_actor_id": actor_id
        }).execute().data

    def acknowledge_ticket(self, ticket_id, technician_id, name):
        now_iso = datetime.now(timezone.utc).isoformat()
        res = get_supabase().table("tickets").update({
            "status": "in_progress",
            "acknowledged_by": technician_id, 
            "acknowledged_name": name, 
            "acknowledged_at": now_iso,
            "updated_at": now_iso
        }).eq("id", ticket_id).execute().data

        try:
            get_supabase().table("ticket_history").insert({
                "ticket_id": ticket_id,
                "status": "in_progress",
                "remarks": f"Started work (Acknowledged by {name or 'Technician'})",
                "changed_by": technician_id
            }).execute()
        except Exception:
            pass

        return res

    def add_follower(self, ticket_id, user_id):
        get_supabase().table("ticket_followers").upsert({"ticket_id": ticket_id, "user_id": user_id}, on_conflict="ticket_id,user_id").execute()

    def remove_follower(self, ticket_id, user_id):
        get_supabase().table("ticket_followers").delete().eq("ticket_id", ticket_id).eq("user_id", user_id).execute()

    def add_supporter(self, ticket_id, user_id):
        get_supabase().table("ticket_supporters").upsert({"ticket_id": ticket_id, "user_id": user_id}, on_conflict="ticket_id,user_id").execute()

class AppointmentRepository:
    def create(self, ticket_id, proposed_by, starts_at, ends_at):
        return get_supabase().table("ticket_appointments").insert({
            "ticket_id": ticket_id, "proposed_by": proposed_by, 
            "starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat()
        }).execute().data

    def get_pending(self, ticket_id):
        return get_supabase().table("ticket_appointments").select("id").eq("ticket_id", ticket_id).eq("decision", "pending").order("created_at", desc=True).limit(1).execute().data

    def update_decision(self, appointment_id, decision):
        return get_supabase().table("ticket_appointments").update({"decision": decision}).eq("id", appointment_id).execute().data

class FeedbackRepository:
    def submit(self, ticket_id, user_id, rating, comment):
        result = get_supabase().rpc("submit_ticket_feedback", {
            "p_ticket_id": ticket_id, "p_user_id": user_id, "p_rating": rating, "p_comment": comment
        }).execute().data
        return result[0] if isinstance(result, list) and result else result

class MediaRepository:
    def create(self, media_data):
        return get_supabase().table("ticket_media").insert(media_data).execute().data

    def get_by_id(self, media_id):
        res = get_supabase().table("ticket_media").select("*").eq("id", media_id).maybe_single().execute()
        return res.data if res else None

    def delete(self, media_id):
        return get_supabase().table("ticket_media").delete().eq("id", media_id).execute().data

class MessageRepository:
    def get_user_messages(self, user_id, offset, limit):
        sent = get_supabase().table("messages").select("*").eq("sender_id", user_id).range(offset, offset + limit - 1).execute().data or []
        received = get_supabase().table("messages").select("*").eq("recipient_id", user_id).range(offset, offset + limit - 1).execute().data or []
        return sent + [m for m in received if m["id"] not in {s["id"] for s in sent}]

    def get_thread(self, thread_id: str):
        try:
            rows = get_supabase().table("messages").select("*").eq("thread_id", thread_id).order("created_at").execute().data or []
        except Exception:
            return []
        if not rows:
            return []
        sender_ids = list({r["sender_id"] for r in rows if r.get("sender_id")})
        if sender_ids:
            try:
                users = get_supabase().table("users").select("clerk_id, full_name, email, role").in_("clerk_id", sender_ids).execute().data or []
                user_map = {u["clerk_id"]: u for u in users}
                for r in rows:
                    u = user_map.get(r.get("sender_id"))
                    if u:
                        r["sender_name"] = u.get("full_name") or u.get("email", "").split("@")[0]
                        r["sender_role"] = u.get("role")
            except Exception:
                pass
        return rows

    def get_admin_messages(self, offset: int = 0, limit: int = 50):
        try:
            return get_supabase().table("messages").select("*").order("created_at", desc=True).range(offset, offset + limit - 1).execute().data or []
        except Exception:
            return []

    def mark_read(self, message_id: str):
        try:
            return get_supabase().table("messages").update({"read_at": datetime.now(timezone.utc).isoformat()}).eq("id", message_id).execute().data
        except Exception:
            return []

    def create(self, message_data):
        return get_supabase().table("messages").insert(message_data).execute().data

class NoticeRepository:
    def get_active(self, offset, limit):
        return get_supabase().table("notices").select("*").eq("active", True).order("created_at", desc=True).range(offset, offset + limit - 1).execute().data or []

    def create(self, notice_data):
        return get_supabase().table("notices").insert(notice_data).execute().data

class AuditRepository:
    def get_logs(self, offset, limit):
        return get_supabase().table("audit_logs").select("*").order("created_at", desc=True).range(offset, offset + limit - 1).execute().data or []

    def log_action(self, actor_id: str, action: str, resource_type: str, resource_id: str, details: dict):
        try:
            return get_supabase().table("audit_logs").insert({
                "actor_id": actor_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": str(resource_id) if resource_id is not None else None,
                "details": details or {}
            }).execute().data
        except Exception:
            return None

    def stream_all_logs(self):
        return get_supabase().table("audit_logs").select("*").order("created_at", desc=True).limit(1000).execute().data or []

    def delete_older_than(self, days: int):
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return get_supabase().table("audit_logs").delete().lt("created_at", cutoff).execute().data or []

user_repo = UserRepository()
ticket_repo = TicketRepository()
appointment_repo = AppointmentRepository()
feedback_repo = FeedbackRepository()
media_repo = MediaRepository()
message_repo = MessageRepository()
notice_repo = NoticeRepository()
audit_repo = AuditRepository()

class DepartmentRepository:
    def get_all(self):
        return get_supabase().table("departments").select("*").order("name").execute().data or []
        
    def create(self, name, description):
        return get_supabase().table("departments").insert({"name": name, "description": description}).execute().data

class CategoryRepository:
    def get_by_department(self, department_id):
        return get_supabase().table("categories").select("*").eq("department_id", department_id).order("name").execute().data or []
        
    def create(self, department_id, name, description):
        return get_supabase().table("categories").insert({"department_id": department_id, "name": name, "description": description}).execute().data

department_repo = DepartmentRepository()
category_repo = CategoryRepository()

class SettingsRepository:
    def get(self):
        data = get_supabase().table("settings").select("*").eq("id", 1).execute().data
        if not data:
            get_supabase().table("settings").insert({"id": 1, "config": {}}).execute()
            return {}
        return data[0]["config"]
        
    def update(self, config):
        data = get_supabase().table("settings").upsert({"id": 1, "config": config, "updated_at": "now()"}).execute().data
        return data[0]["config"] if data else config

settings_repo = SettingsRepository()
