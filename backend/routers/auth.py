"""POST /api/reset-password — admin password reset (no email link needed)."""

import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import settings

logger = logging.getLogger("routers.auth")

router = APIRouter(prefix="/api", tags=["auth"])


class ResetPasswordRequest(BaseModel):
    email: str = Field(..., min_length=5)
    new_password: str = Field(..., min_length=6)


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(503, "Password reset is not configured on this server.")

    email = body.email.strip().lower()
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        # 1. Find the user by email via the Supabase Admin API.
        list_resp = await client.get(
            f"{settings.supabase_url}/auth/v1/admin/users",
            headers=headers,
        )
        if list_resp.status_code != 200:
            logger.error("Supabase admin list users failed: %s", list_resp.text)
            raise HTTPException(500, "Could not reach the auth service.")

        data = list_resp.json()
        users = data.get("users", data) if isinstance(data, dict) else data
        user = next((u for u in users if u.get("email", "").lower() == email), None)

        if not user:
            raise HTTPException(404, "No account found with that email.")

        user_id = user["id"]

        # 2. Update the password via the admin endpoint.
        update_resp = await client.put(
            f"{settings.supabase_url}/auth/v1/admin/users/{user_id}",
            headers=headers,
            json={"password": body.new_password},
        )
        if update_resp.status_code != 200:
            logger.error("Supabase admin update user failed: %s", update_resp.text)
            raise HTTPException(500, "Could not update the password.")

    return {"message": "Password updated successfully."}
