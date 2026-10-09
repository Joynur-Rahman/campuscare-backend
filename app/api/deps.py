import httpx
from datetime import datetime, timezone
from fastapi import Depends, HTTPException
from app.core.clerk import get_current_claims
from app.core.config import settings
from app.core.supabase import get_supabase
from app.schemas import Role
from app.services.repositories import settings_repo, user_repo

def _attach_duty(profile: dict | None) -> dict | None:
    if profile and profile.get("role") == Role.staff.value:
        config = settings_repo.get()
        duty_statuses = config.get("technician_duty", {}) if isinstance(config, dict) else {}
        cid = profile.get("clerk_id")
        email = (profile.get("email") or "").lower()
        profile["status"] = duty_statuses.get(cid) or duty_statuses.get(email) or "On Duty"
    return profile

def fetch_clerk_user(user_id: str) -> dict:
    secret = settings.clerk_secret_key or settings.clerk_webhook_secret
    if not secret or not secret.startswith("sk_"):
        return {}
    try:
        res = httpx.get(
            f"https://api.clerk.com/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=5.0
        )
        if res.status_code == 200:
            data = res.json()
            emails = data.get("email_addresses", [])
            primary_id = data.get("primary_email_address_id")
            email = next((e.get("email_address") for e in emails if e.get("id") == primary_id), None)
            if not email and emails:
                email = emails[0].get("email_address")
            name = " ".join(part for part in (data.get("first_name"), data.get("last_name")) if part)
            return {"email": (email or "").lower().strip(), "name": name or ""}
    except Exception:
        pass
    return {}

def resolve_or_link_user(user_id: str, email_hint: str | None = None, name_hint: str | None = None) -> dict:
    sb = get_supabase()
    # 1. Direct match by clerk_id
    profile = user_repo.get_by_clerk_id(user_id)
    if profile and profile.get("email"):
        role = profile.get("role")
        p_email = (profile.get("email") or "").lower().strip()
        if role in ("student", "faculty") and not (p_email.endswith("@iiitg.ac.in") or p_email.endswith(".iiitg.ac.in")):
            raise HTTPException(
                status_code=403,
                detail="Public registration is restricted to @iiitg.ac.in accounts. Worker and technician accounts must be created by the Administrator."
            )
        return _attach_duty(profile)

    # 2. Extract email from hints or Clerk API
    email = (email_hint or "").lower().strip()
    name = (name_hint or "").strip()
    if not email:
        clerk_data = fetch_clerk_user(user_id)
        email = clerk_data.get("email", "").lower().strip()
        if not name:
            name = clerk_data.get("name", "")

    # 3. Check if an account was pre-created with this email (e.g. by admin)
    if email:
        existing = sb.table("users").select("*").eq("email", email).maybe_single().execute()
        if existing and existing.data:
            pre_created = existing.data
            old_clerk_id = pre_created["clerk_id"]
            if old_clerk_id != user_id:
                # Link old pre-provisioned ID to the real Clerk ID
                if profile:
                    try:
                        sb.table("users").delete().eq("clerk_id", user_id).execute()
                    except Exception:
                        pass

                try:
                    sb.table("tickets").update({"assigned_to": user_id}).eq("assigned_to", old_clerk_id).execute()
                except Exception:
                    pass

                try:
                    sb.table("users").update({
                        "clerk_id": user_id,
                        "full_name": pre_created.get("full_name") or name,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }).eq("email", email).execute()
                except Exception:
                    pass

                return _attach_duty(user_repo.get_by_clerk_id(user_id) or pre_created)

    # 4. If user already had a profile with clerk_id, update email/name if missing
    if profile:
        if email and not profile.get("email"):
            user_repo.update(user_id, {"email": email, "full_name": profile.get("full_name") or name})
            profile["email"] = email
        role = profile.get("role")
        p_email = (profile.get("email") or "").lower().strip()
        if role in ("student", "faculty") and not (p_email.endswith("@iiitg.ac.in") or p_email.endswith(".iiitg.ac.in")):
            raise HTTPException(
                status_code=403,
                detail="Public registration is restricted to @iiitg.ac.in accounts. Worker and technician accounts must be created by the Administrator."
            )
        return _attach_duty(profile)

    # 5. Otherwise, new user -> ONLY allow @iiitg.ac.in domain self-signup
    domain_allowed = email and (email.endswith("@iiitg.ac.in") or email.endswith(".iiitg.ac.in"))
    if not domain_allowed:
        raise HTTPException(
            status_code=403,
            detail="Public registration is restricted to @iiitg.ac.in accounts. Worker and technician accounts must be created by the Administrator."
        )

    new_profile = {
        "clerk_id": user_id,
        "email": email,
        "full_name": name,
        "role": "student",
    }
    user_repo.create(new_profile)
    return {**new_profile, "clerk_id": user_id}

def current_supabase_user(claims: dict = Depends(get_current_claims)) -> dict:
    user_id = claims["sub"]
    email_hint = claims.get("email")
    return resolve_or_link_user(user_id, email_hint=email_hint)

def require_supabase_role(*roles: Role):
    def dependency(user: dict = Depends(current_supabase_user)) -> dict:
        if user.get("role") not in {role.value for role in roles}:
            raise HTTPException(status_code=403, detail="Insufficient role for this operation")
        return user
    return dependency
