# update_assistant.py
import os
import time
import httpx
from sqlmodel import Session, select
from openai import OpenAI
from dotenv import load_dotenv
from models import UserTokens
from main import engine  # Sua base de dados FastAPI
from typing import Dict

load_dotenv()

# Configurações
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")

if not OPENAI_API_KEY or not OPENAI_ASSISTANT_ID:
    raise ValueError("OPENAI_API_KEY ou OPENAI_ASSISTANT_ID não configurada")

client = OpenAI(api_key=OPENAI_API_KEY)

# ----------------------
# Funções de produção
# ----------------------
async def refresh_google_token(user_id: str) -> str:
    """Obtém token válido do Google para o usuário"""
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
    """Obtém token válido da Microsoft para o usuário"""
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

# ----------------------
# Funções chamadas pelo Assistant
# ----------------------
async def listar_eventos_google(user_id: str, dias: int = 7):
    token = await refresh_google_token(user_id)
    async with httpx.AsyncClient() as client_http:
        resp = await client_http.get(
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events",
            params={"maxResults": dias, "singleEvents": True, "orderBy": "startTime"},
            headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        return resp.json().get("items", [])

async def criar_evento_google(user_id: str, titulo: str, data_inicio: str, data_fim: str, descricao: str = "", local: str = ""):
    token = await refresh_google_token(user_id)
    payload = {
        "summary": titulo,
        "description": descricao,
        "location": local,
        "start": {"dateTime": data_inicio},
        "end": {"dateTime": data_fim}
    }
    async with httpx.AsyncClient() as client_http:
        resp = await client_http.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            json=payload,
            headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        return resp.json()

async def listar_eventos_ms(user_id: str, dias: int = 7):
    token = await refresh_ms_token(user_id)
    async with httpx.AsyncClient() as client_http:
        resp = await client_http.get(
            f"https://graph.microsoft.com/v1.0/me/events?$top={dias}",
            headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        return resp.json().get("value", [])

async def criar_evento_ms(user_id: str, titulo: str, data_inicio: str, data_fim: str, descricao: str = "", local: str = ""):
    token = await refresh_ms_token(user_id)
    payload = {
        "subject": titulo,
        "body": {"contentType": "HTML", "content": descricao},
        "start": {"dateTime": data_inicio, "timeZone": "UTC"},
        "end": {"dateTime": data_fim, "timeZone": "UTC"},
        "location": {"displayName": local},
    }
    async with httpx.AsyncClient() as client_http:
        resp = await client_http.post(
            "https://graph.microsoft.com/v1.0/me/events",
            json=payload,
            headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        return resp.json()

# ----------------------
# Atualização do Assistant
# ----------------------
tools = [
    {
        "type": "function",
        "function": {
            "name": "listar_eventos_google",
            "description": "Lista eventos do Google Calendar do usuário",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "ID do usuário"},
                    "dias": {"type": "integer", "description": "Número de dias à frente (padrão: 7)"}
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "criar_evento_google",
            "description": "Cria evento no Google Calendar do usuário",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "titulo": {"type": "string"},
                    "data_inicio": {"type": "string"},
                    "data_fim": {"type": "string"},
                    "descricao": {"type": "string"},
                    "local": {"type": "string"}
                },
                "required": ["user_id", "titulo", "data_inicio", "data_fim"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "listar_eventos_ms",
            "description": "Lista eventos do Microsoft Calendar do usuário",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "dias": {"type": "integer"}
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "criar_evento_ms",
            "description": "Cria evento no Microsoft Calendar do usuário",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "titulo": {"type": "string"},
                    "data_inicio": {"type": "string"},
                    "data_fim": {"type": "string"},
                    "descricao": {"type": "string"},
                    "local": {"type": "string"}
                },
                "required": ["user_id", "titulo", "data_inicio", "data_fim"]
            }
        }
    }
]

# ----------------------
# Função de atualização
# ----------------------
def update_assistant():
    """Atualiza o assistant com as funções de produção"""
    try:
        assistant = client.beta.assistants.retrieve(OPENAI_ASSISTANT_ID)
        print(f"Assistant atual: {assistant.name}")
        updated_assistant = client.beta.assistants.update(
            assistant.id,
            tools=tools,
            model="gpt-4-1106-preview"
        )
        print("✅ Assistant atualizado com sucesso!")
        print(f"Total de functions: {len(updated_assistant.tools)}")
        for i, tool in enumerate(updated_assistant.tools, 1):
            if tool.type == "function":
                print(f"{i}. {tool.function.name}")
    except Exception as e:
        print(f"❌ Erro ao atualizar assistant: {e}")

if __name__ == "__main__":
    update_assistant()
