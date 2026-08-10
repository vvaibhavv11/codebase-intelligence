from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
import httpx

from backend.config import settings

router = APIRouter(tags=["auth"])


@router.get("/auth/github/login")
async def github_login():
    """Redirect user to GitHub OAuth authorization page."""
    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={settings.github_client_id}"
        f"&scope=repo read:user"
        f"&redirect_uri={settings.backend_url}/api/auth/github/callback"
    )
    return RedirectResponse(url=github_auth_url)


@router.get("/auth/github/callback")
async def github_callback(code: str = Query(...)):
    """Exchange the OAuth code for an access token and redirect to frontend."""
    async with httpx.AsyncClient() as client:
        # Exchange code for token
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )

        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange code")

        data = response.json()
        access_token = data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=400,
                detail=data.get("error_description", "Failed to get access token"),
            )

        # Get user info
        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        user_data = user_response.json()

    # Redirect to frontend with token
    redirect_url = (
        f"{settings.frontend_url}/auth/callback"
        f"?token={access_token}"
        f"&username={user_data.get('login', '')}"
        f"&avatar={user_data.get('avatar_url', '')}"
    )
    return RedirectResponse(url=redirect_url)
