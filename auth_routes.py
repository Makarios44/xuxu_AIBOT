# auth_routes.py
import os
import time
import httpx
from fastapi import APIRouter, Request, HTTPException
from sqlmodel import Session, create_engine
from models import UserTokens
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# ✅ Engine LOCAL - não importar do main para evitar dependência circular
database_url = os.getenv("DATABASE_URL", "sqlite:///./database.db")
engine = create_engine(database_url)

# Variáveis de ambiente
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "https://xuxu-bot.onrender.com/auth/callback")

# Verificar se variáveis necessárias estão configuradas
if not all([GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET]):
    logger.warning("⚠️ Variáveis OAuth não configuradas - rotas de calendário não funcionarão")

# ---------------------------
# Login Google
# ---------------------------
@router.get("/auth/google")
async def login_google():
    """Inicia fluxo OAuth do Google Calendar"""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Google OAuth não configurado")
    
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=https://www.googleapis.com/auth/calendar"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&state=google"  # Identificar provider no callback
    )
    return {"auth_url": auth_url}

# ---------------------------
# Login Microsoft
# ---------------------------
@router.get("/auth/microsoft")
async def login_microsoft():
    """Inicia fluxo OAuth do Microsoft Calendar"""
    if not MICROSOFT_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Microsoft OAuth não configurado")
    
    auth_url = (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
        f"client_id={MICROSOFT_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_mode=query"
        f"&scope=offline_access%20Calendars.ReadWrite"
        f"&state=microsoft"  # Identificar provider no callback
    )
    return {"auth_url": auth_url}

# ---------------------------
# Callback genérico (Google/MS) - Corrigido
# ---------------------------
@router.get("/auth/callback")
async def auth_callback(code: str, state: str, request: Request):
    """
    Callback OAuth para Google e Microsoft
    Usa 'state' para identificar o provider
    """
    logger.info(f"Callback recebido - Provider: {state}, Code: {code[:10]}...")
    
    token_url = ""
    data = {}

    if state == "google":
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            raise HTTPException(status_code=500, detail="Google OAuth não configurado")
            
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    elif state == "microsoft":
        if not MICROSOFT_CLIENT_ID or not MICROSOFT_CLIENT_SECRET:
            raise HTTPException(status_code=500, detail="Microsoft OAuth não configurado")
            
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
        raise HTTPException(status_code=400, detail="Provider inválido")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(token_url, data=data)
            resp.raise_for_status()
            token_data = resp.json()
            
        logger.info(f"Token obtido com sucesso para {state}")

        # Salvar tokens no banco
        user_id = "user-demo"  # 👉 Você pode obter do contexto do Teams depois
        with Session(engine) as session:
            # Verificar se já existe token para este usuário/provider
            existing_token = session.exec(
                UserTokens.select().where(
                    UserTokens.user_id == user_id, 
                    UserTokens.provider == state
                )
            ).first()
            
            if existing_token:
                # Atualizar token existente
                existing_token.access_token = token_data["access_token"]
                existing_token.refresh_token = token_data.get("refresh_token", existing_token.refresh_token)
                existing_token.expires_at = time.time() + token_data.get("expires_in", 3600)
                session.add(existing_token)
            else:
                # Criar novo token
                token = UserTokens(
                    user_id=user_id,
                    provider=state,
                    access_token=token_data["access_token"],
                    refresh_token=token_data.get("refresh_token"),
                    expires_at=time.time() + token_data.get("expires_in", 3600),
                )
                session.add(token)
            
            session.commit()

        return {
            "status": "success", 
            "provider": state, 
            "user_id": user_id,
            "message": "Autenticação realizada com sucesso! Volte ao Teams."
        }

    except httpx.HTTPError as e:
        logger.error(f"Erro OAuth {state}: {e}")
        raise HTTPException(status_code=400, detail=f"Erro na autenticação: {e}")
    except Exception as e:
        logger.error(f"Erro inesperado: {e}")
        raise HTTPException(status_code=500, detail="Erro interno no servidor")

# ---------------------------
# Rotas auxiliares
# ---------------------------
@router.get("/auth/status")
async def auth_status(user_id: str = "user-demo"):
    """Verifica status de autenticação do usuário"""
    with Session(engine) as session:
        tokens = session.exec(
            UserTokens.select().where(UserTokens.user_id == user_id)
        ).all()
        
        status = {}
        for token in tokens:
            status[token.provider] = {
                "authenticated": True,
                "expires_at": token.expires_at,
                "expired": time.time() > token.expires_at
            }
        
        return {"user_id": user_id, "auth_status": status}

@router.delete("/auth/logout")
async def logout(provider: str, user_id: str = "user-demo"):
    """Remove autenticação do usuário"""
    with Session(engine) as session:
        token = session.exec(
            UserTokens.select().where(
                UserTokens.user_id == user_id,
                UserTokens.provider == provider
            )
        ).first()
        
        if token:
            session.delete(token)
            session.commit()
            return {"status": "success", "message": f"Logout realizado para {provider}"}
        else:
            raise HTTPException(status_code=404, detail="Token não encontrado")