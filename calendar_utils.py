import datetime

# --- GOOGLE CALENDAR ---
async def criar_evento_google(titulo: str, data_inicio: str, data_fim: str):
    return {"status": "ok", "msg": f"Evento '{titulo}' criado no Google Calendar de {data_inicio} a {data_fim}"}

async def listar_eventos_google(dias: int = 7):
    return {"status": "ok", "eventos": [f"Evento teste Google +{i} dias" for i in range(dias)]}

# --- MICROSOFT CALENDAR ---
async def criar_evento_ms(user_email: str, titulo: str, data_inicio: str, data_fim: str):
    return {"status": "ok", "msg": f"Evento '{titulo}' criado no MS Calendar ({user_email})"}

async def listar_eventos_ms(user_email: str, dias: int = 7):
    return {"status": "ok", "eventos": [f"Evento teste MS +{i} dias para {user_email}" for i in range(dias)]}
