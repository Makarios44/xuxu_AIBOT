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
import httpx

# Importações locais corrigidas
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
ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bot_memory.db")

if not OPENAI_API_KEY or not ASSISTANT_ID:
    raise ValueError("⚠️ Configure OPENAI_API_KEY e OPENAI_ASSISTANT_ID no .env")

# Clients
client = AsyncOpenAI(api_key=OPENAI_API_KEY)
adapter_settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
adapter = BotFrameworkAdapter(adapter_settings)

# FastAPI
app = FastAPI(title="Xuxu Bot - Teams + OpenAI Assistant")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://teams.microsoft.com", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Threads em memória (para produção use Redis)
_threads: dict[str, str] = {}

# Database initialization
@app.on_event("startup")
async def startup_event():
    create_db_and_tables()

async def get_or_create_thread(conversation_id: str) -> str:
    if conversation_id in _threads:
        return _threads[conversation_id]
    thread = await client.beta.threads.create()
    _threads[conversation_id] = thread.id
    return thread.id

def save_message(conversation_id: str, role: str, content: str):
    with Session(engine) as session:
        mem = ConversationMemory(conversation_id=conversation_id, role=role, content=content)
        session.add(mem)
        session.commit()

# -------------------------------
# Function Dispatcher
# -------------------------------
async def dispatch_tool_call(name: str, args: dict, user_id: str = "") -> str:
    try:
        if name == "criar_evento_google":
            result = await criar_evento_google(
                user_id,  # Adicione user_id aqui
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
                user_id,  # Use user_id em vez de user_email
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
# Endpoints REST
# -------------------------------
@app.post("/assistant/message")
async def send_message(request: AssistantRequest):
    """Envia mensagem para o assistant e retorna a resposta."""
    try:
        thread_id = await get_or_create_thread("prod_" + request.user_id)
        
        await client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=request.mensagem,
        )
        
        run = await client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID,
        )
        
        # Process tool calls if needed
        while True:
            run_status = await client.beta.threads.runs.retrieve(
                thread_id=thread_id, 
                run_id=run.id
            )
            
            if run_status.status == "requires_action":
                tool_outputs = []
                for tool_call in run_status.required_action.submit_tool_outputs.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    output = await dispatch_tool_call(
                        function_name, 
                        function_args, 
                        request.user_id
                    )
                    
                    tool_outputs.append({
                        "tool_call_id": tool_call.id,
                        "output": str(output)
                    })
                
                await client.beta.threads.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=tool_outputs
                )
                
            elif run_status.status in ["completed", "failed", "cancelled", "expired"]:
                break
                
            await asyncio.sleep(1)
        
        # Get the response
        messages = await client.beta.threads.messages.list(thread_id=thread_id)
        for msg in reversed(messages.data):
            if msg.role == "assistant" and msg.content:
                return {"resposta": msg.content[0].text.value}
        
        return {"resposta": "❌ Não consegui gerar resposta."}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/calendar/google/create")
async def create_google_event(user_id: str, event: EventCreate):
    """Cria evento no Google Calendar"""
    try:
        token = await refresh_google_token(user_id)
        # Implemente a criação real do evento aqui
        return {"status": "success", "message": "Evento criado no Google Calendar"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/calendar/ms/create")
async def create_ms_event(user_id: str, event: EventCreate):
    """Cria evento no Microsoft Calendar"""
    try:
        token = await refresh_ms_token(user_id)
        # Implemente a criação real do evento aqui
        return {"status": "success", "message": "Evento criado no Microsoft Calendar"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------------
# Chamando o Assistant
# -------------------------------
async def call_openai_agent(conversation_id: str, user_message: str, user_id: str = "") -> str:
    thread_id = await get_or_create_thread(conversation_id)

    await client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_message,
    )

    run = await client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=ASSISTANT_ID,
    )

    while True:
        run_status = await client.beta.threads.runs.retrieve(
            thread_id=thread_id, 
            run_id=run.id
        )

        if run_status.status == "requires_action":
            tool_outputs = []
            for tool_call in run_status.required_action.submit_tool_outputs.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                output = await dispatch_tool_call(
                    function_name, 
                    function_args, 
                    user_id
                )
                
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": str(output)
                })
            
            await client.beta.threads.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )
            
        elif run_status.status in ["completed", "failed", "cancelled", "expired"]:
            break

        await asyncio.sleep(1)

    messages = await client.beta.threads.messages.list(thread_id=thread_id)
    for msg in reversed(messages.data):
        if msg.role == "assistant" and msg.content:
            return msg.content[0].text.value

    return "❌ Não consegui gerar resposta."

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

@app.post("/api/messages")
async def messages(req: Request):
    """Endpoint principal para mensagens do Teams"""
    body = await req.json()
    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")

    async def aux_func(turn_context: TurnContext):
        await bot.on_turn(turn_context)

    try:
        response = await adapter.process_activity(activity, auth_header, aux_func)
        if response:
            return JSONResponse(content=response.body, status_code=response.status)
        return Response(status_code=201)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "Xuxu Bot API"}

@app.get("/memory/{conversation_id}")
async def read_memory(conversation_id: str):
    with Session(engine) as session:
        stmt = select(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
        results = session.exec(stmt).all()
        return [{"role": r.role, "content": r.content} for r in results]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)