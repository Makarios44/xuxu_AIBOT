# token_utils.py
import time
import httpx
from sqlmodel import Session, select
from models import UserTokens
from database import engine  
import os

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")

async def refresh_google_token(user_id: str) -> str:
    """Retorna token válido do Google para o usuário"""
    with Session(engine) as session:
        token = session.exec(
            select(UserTokens).where(UserTokens.user_id == user_id, UserTokens.provider == "google")
        ).first()
        if not token:
            raise Exception("Token Google não encontrado")
        if token.expires_at and token.expires_at > time.time():
            return token.access_token

        url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": token.refresh_token,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient() as client_http:
            resp = await client_http.post(url, data=data)
            resp.raise_for_status()
            new_data = resp.json()

        token.access_token = new_data["access_token"]
        token.expires_at = time.time() + new_data.get("expires_in", 3600)
        session.add(token)
        session.commit()
        return token.access_token

async def refresh_ms_token(user_id: str) -> str:
    """Retorna token válido da Microsoft para o usuário"""
    with Session(engine) as session:
        token = session.exec(
            select(UserTokens).where(UserTokens.user_id == user_id, UserTokens.provider == "microsoft")
        ).first()
        if not token:
            raise Exception("Token Microsoft não encontrado")
        if token.expires_at and token.expires_at > time.time():
            return token.access_token

        url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        data = {
            "client_id": MICROSOFT_CLIENT_ID,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "refresh_token": token.refresh_token,
            "grant_type": "refresh_token",
            "scope": "https://graph.microsoft.com/.default",
        }
        async with httpx.AsyncClient() as client_http:
            resp = await client_http.post(url, data=data)
            resp.raise_for_status()
            new_data = resp.json()

        token.access_token = new_data["access_token"]
        token.expires_at = time.time() + new_data.get("expires_in", 3600)
        session.add(token)
        session.commit()
        return token.access_token