import os
import time
import httpx
from fastapi import APIRouter, Request
from sqlmodel import Session
from models import UserTokens
from main import engine

router = APIRouter()

# Variáveis de ambiente
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")

# ---------------------------
# Login Google
# ---------------------------
@router.get("/auth/google")
async def login_google():
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=https://www.googleapis.com/auth/calendar"
        f"&access_type=offline"
        f"&prompt=consent"
    )
    return {"auth_url": auth_url}


# ---------------------------
# Login Microsoft
# ---------------------------
@router.get("/auth/microsoft")
async def login_microsoft():
    auth_url = (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
        f"client_id={MICROSOFT_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_mode=query"
        f"&scope=offline_access%20Calendars.ReadWrite"
    )
    return {"auth_url": auth_url}


# ---------------------------
# Callback genérico (Google/MS)
# ---------------------------
@router.get("/auth/callback")
async def auth_callback(provider: str, code: str, request: Request):
    token_url = ""
    data = {}

    if provider == "google":
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    elif provider == "microsoft":
        token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        data = {
            "client_id": MICROSOFT_CLIENT_ID,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
            "scope": "offline_access Calendars.ReadWrite",
        }
    else:
        return {"error": "Provider inválido"}

    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data)
        resp.raise_for_status()
        token_data = resp.json()

    # Salvar tokens no banco
    user_id = "user-demo"  # 👉 aqui você pode mapear pelo Teams ID, email, etc.
    with Session(engine) as session:
        token = UserTokens(
            user_id=user_id,
            provider=provider,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=time.time() + token_data.get("expires_in", 3600),
        )
        session.add(token)
        session.commit()

    return {"status": "ok", "provider": provider, "user_id": user_id}
