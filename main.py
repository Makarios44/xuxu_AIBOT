
import os
import json
import asyncio
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
from fastapi import FastAPI, Request, Response
from openai import AsyncOpenAI
from auth_routes import router as auth_router

# Configuração
APP_ID = os.getenv("MICROSOFT_APP_ID", "")
APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Clients
client = AsyncOpenAI(api_key=OPENAI_API_KEY)
adapter_settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
adapter = BotFrameworkAdapter(adapter_settings)

# FastAPI
app = FastAPI(title="Xuxu Bot - Teams + OpenAI")
app.include_router(auth_router)

# Bot simples
class SimpleTeamsBot:
    async def on_turn(self, turn_context: TurnContext):
        if turn_context.activity.type == "message":
            try:
                # Chamar OpenAI
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Você é um assistente útil no Microsoft Teams."},
                        {"role": "user", "content": turn_context.activity.text}
                    ]
                )
                
                reply_text = response.choices[0].message.content
                await turn_context.send_activity(reply_text)
                
            except Exception as e:
                await turn_context.send_activity(f"Desculpe, erro: {str(e)}")

bot = SimpleTeamsBot()

# Endpoint principal
@app.post("/api/messages")
async def messages(req: Request):
    """Endpoint principal para mensagens do Teams"""
    try:
        body = await req.json()
    except json.JSONDecodeError:
        return Response(content="", status_code=200)
    
    try:
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")

        async def aux_func(turn_context: TurnContext):
            await bot.on_turn(turn_context)

        response = await adapter.process_activity(activity, auth_header, aux_func)
        
        if response:
            return Response(
                content=json.dumps(response.body),
                status_code=response.status,
                media_type="application/json"
            )
        return Response(status_code=201)
        
    except Exception as e:
        print(f"Erro no processamento: {e}")
        return Response(status_code=200)

# Health checks
@app.get("/")
async def root():
    return {"status": "online", "service": "Xuxu Bot"}

@app.get("/healthz")
async def healthz():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
