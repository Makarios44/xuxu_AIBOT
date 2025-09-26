# main.py
import os
import asyncio
import json
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from botbuilder.core import TurnContext, BotFrameworkAdapter, BotFrameworkAdapterSettings
from botbuilder.schema import Activity
from sqlmodel import Session, select
from dotenv import load_dotenv
from openai import AsyncOpenAI
from fastapi.middleware.cors import CORSMiddleware

# Importações locais
from database import engine, create_db_and_tables
from models import ConversationMemory
from schemas import EventCreate, AssistantRequest
from calendar_utils import (
    criar_evento_google,
    listar_eventos_google,
    criar_evento_ms,
    listar_eventos_ms
)
from token_utils import refresh_google_token, refresh_ms_token

load_dotenv()

# Config
APP_ID = os.getenv("MICROSOFT_APP_ID", "")
APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

if not OPENAI_API_KEY:
    raise ValueError("⚠️ Configure OPENAI_API_KEY no .env")

# Clients
client = AsyncOpenAI(api_key=OPENAI_API_KEY)
adapter_settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
adapter = BotFrameworkAdapter(adapter_settings)

# FastAPI
app = FastAPI(title="Xuxu Bot - Teams + OpenAI")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://teams.microsoft.com", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database initialization
@app.on_event("startup")
async def startup_event():
    create_db_and_tables()


def save_message(conversation_id: str, role: str, content: str):
    with Session(engine) as session:
        mem = ConversationMemory(conversation_id=conversation_id, role=role, content=content)
        session.add(mem)
        session.commit()


def get_conversation_history(conversation_id: str):
    """Recupera histórico de mensagens de uma conversa do banco."""
    with Session(engine) as session:
        stmt = select(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
        results = session.exec(stmt).all()
        return [{"role": r.role, "content": r.content} for r in results]


# -------------------------------
# Function Dispatcher
# -------------------------------
async def dispatch_tool_call(name: str, args: dict, user_id: str = "") -> str:
    try:
        if name == "criar_evento_google":
            result = await criar_evento_google(
                user_id,
                args["titulo"],
                args["data_inicio"],
                args["data_fim"],
                args.get("descricao", ""),
                args.get("local", "")
            )
            return f"✅ Evento criado no Google Calendar: {result.get('summary', 'Sucesso')}"

        elif name == "listar_eventos_google":
            eventos = await listar_eventos_google(user_id, args.get("dias", 7))
            return f"📅 Eventos Google: {len(eventos)} encontrados"

        elif name == "criar_evento_calendar":
            result = await criar_evento_ms(
                user_id,
                args["titulo"],
                args["data_inicio"],
                args["data_fim"],
                args.get("descricao", ""),
                args.get("local", "")
            )
            return f"✅ Evento criado no Microsoft Calendar: {result.get('subject', 'Sucesso')}"

        elif name == "listar_eventos_calendar":
            eventos = await listar_eventos_ms(user_id, args.get("dias", 7))
            return f"📅 Eventos Microsoft: {len(eventos)} encontrados"

        elif name == "resumir_texto":
            texto = args["texto"]
            return f"📝 Resumo: {texto[:200]}..."

        else:
            return f"❌ Função {name} não implementada"

    except Exception as e:
        return f"❌ Erro na função {name}: {str(e)}"


# -------------------------------
# OpenAI Call (Chat)
# -------------------------------
async def call_openai_agent(conversation_id: str, user_message: str, user_id: str = "") -> str:
    try:
        # Recupera histórico da conversa
        history = get_conversation_history(conversation_id)

        # Monta mensagens no formato do Chat Completions
        messages = [{"role": "system", "content": "Você é um bot integrado ao Microsoft Teams que ajuda a criar e listar eventos."}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )

        return response.choices[0].message.content
    except Exception as e:
        return f"❌ Erro ao chamar OpenAI: {str(e)}"


# -------------------------------
# Endpoints REST
# -------------------------------
@app.post("/assistant/message")
async def send_message(request: AssistantRequest):
    """Envia mensagem para o assistant e retorna a resposta."""
    try:
        resposta = await call_openai_agent("prod_" + request.user_id, request.mensagem, request.user_id)
        save_message("prod_" + request.user_id, "user", request.mensagem)
        save_message("prod_" + request.user_id, "assistant", resposta)
        return {"resposta": resposta}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/calendar/google/create")
async def create_google_event(user_id: str, event: EventCreate):
    """Cria evento no Google Calendar"""
    try:
        token = await refresh_google_token(user_id)
        return {"status": "success", "message": "Evento criado no Google Calendar"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/calendar/ms/create")
async def create_ms_event(user_id: str, event: EventCreate):
    """Cria evento no Microsoft Calendar"""
    try:
        token = await refresh_ms_token(user_id)
        return {"status": "success", "message": "Evento criado no Microsoft Calendar"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------
# Bot para Teams
# -------------------------------
class SimpleTeamsBot:
    async def on_turn(self, turn_context: TurnContext):
        if turn_context.activity.type == "message":
            text = turn_context.activity.text or ""
            conv_id = turn_context.activity.conversation.id
            user_id = turn_context.activity.from_property.id if turn_context.activity.from_property else ""

            save_message(conv_id, "user", text)

            reply_text = await call_openai_agent(conv_id, text, user_id)

            save_message(conv_id, "assistant", reply_text)
            await turn_context.send_activity(reply_text)


bot = SimpleTeamsBot()


import logging

@app.post("/api/messages")
async def messages(req: Request):
    """Endpoint principal para mensagens do Teams"""
    # Log da requisição recebida
    logging.info(f"Recebida requisição de: {req.client.host}")
    
    try:
        body = await req.json()
        logging.info(f"JSON recebido: {body}")
    except json.JSONDecodeError:
        logging.warning("Requisição sem JSON válido - provavelmente health check")
        return Response(content="", status_code=200)
    
    try:
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")
        
        logging.info(f"Tipo de atividade: {activity.type}")

        async def aux_func(turn_context: TurnContext):
            await bot.on_turn(turn_context)

        response = await adapter.process_activity(activity, auth_header, aux_func)
        
        if response:
            logging.info(f"Resposta enviada: {response.status}")
            return JSONResponse(content=response.body, status_code=response.status)
        
        logging.info("Atividade processada sem resposta específica")
        return Response(status_code=201)
        
    except Exception as e:
        logging.error(f"Erro no processamento: {e}")
        # Importante: sempre retorna 200 para webhooks do Teams
        return Response(status_code=200)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "Xuxu Bot API"}
    
@app.get("/")
async def root():
    return {"status": "ok", "service": "Xuxu Bot API"}
@app.post("/api/messages")
async def messages(req: Request):
    """Endpoint principal para mensagens do Teams"""
    print("=== NOVA REQUISIÇÃO DO TEAMS ===")
    
    # Debug dos headers
    headers = dict(req.headers)
    print(f"Headers: { {k: v for k, v in headers.items() if 'authorization' in k.lower()} }")
    
    try:
        body = await req.json()
        print(f"Body type: {body.get('type')}")
        print(f"Body text: {body.get('text')}")
    except json.JSONDecodeError:
        print("Health check - sem JSON")
        return Response(content="", status_code=200)
    
    try:
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")
        
        print(f"Activity type: {activity.type}")
        print(f"Auth header present: {bool(auth_header)}")
        print(f"APP_ID being used: {APP_ID}")

        async def aux_func(turn_context: TurnContext):
            await bot.on_turn(turn_context)

        response = await adapter.process_activity(activity, auth_header, aux_func)
        
        if response:
            print(f"Resposta enviada: {response.status}")
            return JSONResponse(content=response.body, status_code=response.status)
        
        print("Atividade processada sem resposta específica")
        return Response(status_code=201)
        
    except Exception as e:
        print(f"ERRO DETALHADO: {e}")
        import traceback
        traceback.print_exc()
        return Response(status_code=200)

@app.get("/memory/{conversation_id}")
async def read_memory(conversation_id: str):
    with Session(engine) as session:
        stmt = select(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
        results = session.exec(stmt).all()
        return [{"role": r.role, "content": r.content} for r in results]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
