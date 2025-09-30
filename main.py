
import os
from teams_ai import Application, AI
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings
from botbuilder.schema import Activity
from fastapi import FastAPI, Request, Response
import json
from auth_routes import router as auth_router

# Configuração
APP_ID = os.getenv("MICROSOFT_APP_ID", "")
APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# 1. APLICAÇÃO TEAMS AI (SIMPLES)
app = Application(
    ai=AI(
        openai_api_key=OPENAI_API_KEY,
        model="gpt-4o-mini"
    )
)

# 2. HANDLER PRINCIPAL (SIMPLES)
@app.turn
async def on_turn(context, state):
    if context.activity.type == "message":
        # Sua lógica aqui - MUITO mais simples
        response = await app.ai.complete(context.activity.text)
        await context.send_activity(response)

# 3. FASTAPI E ADAPTER
fastapi_app = FastAPI(title="Xuxu Bot - Teams AI")
adapter_settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
adapter = BotFrameworkAdapter(adapter_settings)
fastapi_app.include_router(auth_router)
# 4. ENDPOINT PRINCIPAL
@fastapi_app.post("/api/messages")
async def messages(req: Request):
    try:
        body = await req.json()
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")
        
        # Processar com Teams AI
        await adapter.process_activity(activity, auth_header, app.run)
        return Response(status_code=200)
        
    except Exception as e:
        print(f"Erro: {e}")
        return Response(status_code=200)

# 5. HEALTH CHECKS
@fastapi_app.get("/")
async def root():
    return {"status": "online", "framework": "Teams AI"}

@fastapi_app.get("/healthz")
async def healthz():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)