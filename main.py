"""
FastAPI + Microsoft Teams Bot + OpenAI Assistant + SQLite + Graph API + Google Calendar
Xuxu - Assistente IA Completa com Integração Microsoft Graph e Google Calendar
"""

import os
import asyncio
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel import SQLModel, Field, create_engine, Session, select
from dotenv import load_dotenv
import httpx

# Bot Framework
from botbuilder.core import TurnContext, BotFrameworkAdapter, BotFrameworkAdapterSettings
from botbuilder.schema import Activity

# OpenAI
from openai import AsyncOpenAI

# Microsoft Graph
from azure.identity import ClientSecretCredential
from msgraph import GraphServiceClient
from msgraph.generated.users.item.events.events_request_builder import EventsRequestBuilder

load_dotenv()

# Config
APP_ID = os.getenv("MICROSOFT_APP_ID", "")
APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bot_memory.db")

# Microsoft Graph
CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
TENANT_ID = os.getenv("TENANT_ID", "")
AUTHORITY = os.getenv("AUTHORITY", f"https://login.microsoftonline.com/{TENANT_ID}")
GRAPH_SCOPES = os.getenv("GRAPH_SCOPES", "https://graph.microsoft.com/.default")

# Google Calendar
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY é obrigatória")
if not OPENAI_ASSISTANT_ID:
    raise ValueError("OPENAI_ASSISTANT_ID é obrigatória")

# OpenAI client
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Microsoft Graph client
graph_credential = None
graph_client = None

if CLIENT_ID and CLIENT_SECRET and TENANT_ID:
    graph_credential = ClientSecretCredential(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    )
    graph_client = GraphServiceClient(credentials=graph_credential)

# SQLite setup
engine = create_engine(DATABASE_URL, echo=False)

class ConversationMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: str
    user_name: Optional[str] = None
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ThreadMapping(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: str = Field(unique=True)
    thread_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class UserTokens(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str
    provider: str  # 'microsoft' ou 'google'
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)

SQLModel.metadata.create_all(engine)

# FastAPI
app = FastAPI(title="Xuxu - Assistente IA Completa + Integrações")

# Bot adapter
adapter_settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
adapter = BotFrameworkAdapter(adapter_settings)

# Helpers
def save_message(conversation_id: str, role: str, content: str, user_name: Optional[str] = None):
    """Salva mensagem no banco de dados"""
    with Session(engine) as session:
        mem = ConversationMemory(
            conversation_id=conversation_id, 
            role=role, 
            content=content,
            user_name=user_name
        )
        session.add(mem)
        session.commit()

def get_conversation_history(conversation_id: str, limit: int = 20) -> List[ConversationMemory]:
    """Recupera histórico da conversa"""
    with Session(engine) as session:
        statement = (
            select(ConversationMemory)
            .where(ConversationMemory.conversation_id == conversation_id)
            .order_by(ConversationMemory.id.desc())
            .limit(limit)
        )
        results = session.exec(statement).all()
        return list(reversed(results))

def save_thread_mapping(conversation_id: str, thread_id: str):
    """Salva mapeamento entre conversa do Teams e thread do OpenAI"""
    with Session(engine) as session:
        mapping = ThreadMapping(conversation_id=conversation_id, thread_id=thread_id)
        session.add(mapping)
        session.commit()

def get_thread_id(conversation_id: str) -> Optional[str]:
    """Recupera thread_id do OpenAI para uma conversa do Teams"""
    with Session(engine) as session:
        statement = select(ThreadMapping).where(ThreadMapping.conversation_id == conversation_id)
        result = session.exec(statement).first()
        return result.thread_id if result else None

def save_user_token(user_id: str, provider: str, access_token: str, refresh_token: str = None, expires_in: int = 3600):
    """Salva token de usuário"""
    with Session(engine) as session:
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        token = UserTokens(
            user_id=user_id,
            provider=provider,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at
        )
        session.add(token)
        session.commit()

def get_user_token(user_id: str, provider: str) -> Optional[UserTokens]:
    """Recupera token de usuário"""
    with Session(engine) as session:
        statement = select(UserTokens).where(
            UserTokens.user_id == user_id,
            UserTokens.provider == provider,
            UserTokens.expires_at > datetime.utcnow()
        )
        return session.exec(statement).first()

# ----------------------
# Microsoft Graph Functions
# ----------------------

async def listar_eventos_calendar_tool(user_email: str, dias: int = 7) -> str:
    """Lista eventos do calendário Microsoft via Graph API"""
    if not graph_client:
        return "❌ Microsoft Graph não está configurado. Configure CLIENT_ID, CLIENT_SECRET e TENANT_ID"
    
    try:
        # Data de início e fim
        start_time = datetime.utcnow()
        end_time = start_time + timedelta(days=dias)
        
        # Busca eventos
        events = await graph_client.users.by_user_id(user_email).calendar.events.get()
        
        if not events or not events.value:
            return f"📅 Nenhum evento encontrado nos próximos {dias} dias para {user_email}"
        
        resultado = f"📅 **EVENTOS DO CALENDÁRIO** ({user_email})\n\n"
        
        for event in events.value[:10]:  # Limita a 10 eventos
            start = event.start.date_time if event.start else "Não definido"
            end = event.end.date_time if event.end else "Não definido"
            location = event.location.display_name if event.location else "Sem local"
            
            resultado += f"🗓️ **{event.subject}**\n"
            resultado += f"📍 {location}\n"
            resultado += f"⏰ {start} → {end}\n"
            if event.body and event.body.content:
                resultado += f"📝 {event.body.content[:100]}...\n"
            resultado += "\n"
        
        return resultado
        
    except Exception as e:
        return f"❌ Erro ao acessar calendário: {str(e)}"

async def criar_evento_calendar_tool(user_email: str, titulo: str, data_inicio: str, data_fim: str, descricao: str = "", local: str = "") -> str:
    """Cria evento no calendário Microsoft"""
    if not graph_client:
        return "❌ Microsoft Graph não está configurado"
    
    try:
        # Converte datas
        start_datetime = datetime.fromisoformat(data_inicio.replace('Z', '+00:00'))
        end_datetime = datetime.fromisoformat(data_fim.replace('Z', '+00:00'))
        
        event_data = {
            "subject": titulo,
            "start": {
                "dateTime": start_datetime.isoformat(),
                "timeZone": "UTC"
            },
            "end": {
                "dateTime": end_datetime.isoformat(),
                "timeZone": "UTC"
            },
            "body": {
                "contentType": "HTML",
                "content": descricao
            }
        }
        
        if local:
            event_data["location"] = {"displayName": local}
        
        # Cria evento
        await graph_client.users.by_user_id(user_email).calendar.events.post(event_data)
        
        return f"✅ Evento '{titulo}' criado com sucesso no calendário de {user_email}!"
        
    except Exception as e:
        return f"❌ Erro ao criar evento: {str(e)}"

async def buscar_usuarios_tool(query: str) -> str:
    """Busca usuários no Azure AD"""
    if not graph_client:
        return "❌ Microsoft Graph não está configurado"
    
    try:
        users = await graph_client.users.get(filter=f"startswith(displayName,'{query}') or startswith(mail,'{query}')")
        
        if not users or not users.value:
            return f"👤 Nenhum usuário encontrado para '{query}'"
        
        resultado = f"👥 **USUÁRIOS ENCONTRADOS** ('{query}')\n\n"
        
        for user in users.value[:10]:
            name = user.display_name or "Nome não disponível"
            email = user.mail or user.user_principal_name or "Email não disponível"
            job_title = user.job_title or "Cargo não informado"
            
            resultado += f"👤 **{name}**\n"
            resultado += f"📧 {email}\n"
            resultado += f"💼 {job_title}\n\n"
        
        return resultado
        
    except Exception as e:
        return f"❌ Erro ao buscar usuários: {str(e)}"

# ----------------------
# Google Calendar Functions
# ----------------------

async def listar_eventos_google_tool(user_id: str, dias: int = 7) -> str:
    """Lista eventos do Google Calendar"""
    token = get_user_token(user_id, "google")
    if not token:
        return "❌ Usuário não autenticado no Google Calendar. Use /auth google"
    
    try:
        headers = {"Authorization": f"Bearer {token.access_token}"}
        
        # Parâmetros da API
        time_min = datetime.utcnow().isoformat() + 'Z'
        time_max = (datetime.utcnow() + timedelta(days=dias)).isoformat() + 'Z'
        
        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        params = {
            "timeMin": time_min,
            "timeMax": time_max,
            "maxResults": 10,
            "singleEvents": True,
            "orderBy": "startTime"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            data = response.json()
        
        if "items" not in data or not data["items"]:
            return f"📅 Nenhum evento encontrado nos próximos {dias} dias"
        
        resultado = f"📅 **GOOGLE CALENDAR** (próximos {dias} dias)\n\n"
        
        for event in data["items"]:
            summary = event.get("summary", "Sem título")
            start = event.get("start", {}).get("dateTime", "Não definido")
            end = event.get("end", {}).get("dateTime", "Não definido")
            location = event.get("location", "Sem local")
            
            resultado += f"🗓️ **{summary}**\n"
            resultado += f"📍 {location}\n"
            resultado += f"⏰ {start} → {end}\n\n"
        
        return resultado
        
    except Exception as e:
        return f"❌ Erro ao acessar Google Calendar: {str(e)}"

async def criar_evento_google_tool(user_id: str, titulo: str, data_inicio: str, data_fim: str, descricao: str = "", local: str = "") -> str:
    """Cria evento no Google Calendar"""
    token = get_user_token(user_id, "google")
    if not token:
        return "❌ Usuário não autenticado no Google Calendar"
    
    try:
        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "Content-Type": "application/json"
        }
        
        event_data = {
            "summary": titulo,
            "description": descricao,
            "start": {"dateTime": data_inicio, "timeZone": "America/Sao_Paulo"},
            "end": {"dateTime": data_fim, "timeZone": "America/Sao_Paulo"}
        }
        
        if local:
            event_data["location"] = local
        
        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=event_data)
            result = response.json()
        
        if response.status_code == 200:
            return f"✅ Evento '{titulo}' criado com sucesso no Google Calendar!"
        else:
            return f"❌ Erro: {result.get('error', {}).get('message', 'Erro desconhecido')}"
        
    except Exception as e:
        return f"❌ Erro ao criar evento: {str(e)}"

# ----------------------
# Tools Originais + Novas
# ----------------------

async def resumir_texto_tool(texto: str, tipo: str = "geral") -> str:
    """Resume qualquer tipo de texto"""
    try:
        if tipo.lower() == "reuniao":
            prompt_template = """Crie um resumo estruturado desta reunião:
            
            📋 **RESUMO DA REUNIÃO**
            
            🎯 **Principais Tópicos:**
            • [Liste os temas principais]
            
            ✅ **Decisões Tomadas:**
            • [Liste as decisões]
            
            📝 **Action Items:**
            • [Liste as tarefas com responsáveis]
            
            🔮 **Próximos Passos:**
            • [Liste os próximos passos]"""
        else:
            prompt_template = """Crie um resumo claro e objetivo deste conteúdo:
            
            📄 **RESUMO**
            
            🎯 **Pontos Principais:**
            • [Liste os pontos mais importantes]
            
            💡 **Insights Chave:**
            • [Liste os insights mais relevantes]
            
            📋 **Conclusões:**
            • [Liste as principais conclusões]"""

        completion = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"Você é a Xuxu, assistente IA especializada em resumir conteúdos. {prompt_template}"},
                {"role": "user", "content": f"Resume este conteúdo:\n\n{texto}"}
            ],
            temperature=0.3
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Erro ao resumir: {str(e)}"

async def analisar_dados_tool(dados: str, tipo_analise: str = "geral") -> str:
    """Analisa dados, números, tendências"""
    try:
        completion = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": """Você é a Xuxu, especialista em análise de dados. 
                    
                    Forneça análises claras com:
                    📊 **ANÁLISE DE DADOS**
                    
                    📈 **Tendências Identificadas:**
                    • [Liste as principais tendências]
                    
                    🔍 **Insights:**
                    • [Insights importantes dos dados]
                    
                    💡 **Recomendações:**
                    • [Sugestões baseadas nos dados]
                    
                    ⚠️ **Pontos de Atenção:**
                    • [O que merece atenção]"""
                },
                {"role": "user", "content": f"Tipo de análise: {tipo_analise}\n\nDados para analisar:\n{dados}"}
            ],
            temperature=0.2
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Erro ao analisar dados: {str(e)}"

async def criar_conteudo_tool(tipo: str, tema: str, detalhes: str = "") -> str:
    """Cria diferentes tipos de conteúdo"""
    try:
        templates = {
            "email": "Crie um email profissional bem estruturado",
            "apresentacao": "Crie um outline para apresentação com tópicos principais",
            "documento": "Crie um documento estruturado e bem formatado",
            "relatorio": "Crie um relatório profissional detalhado",
            "ata": "Crie uma ata de reunião estruturada",
            "proposta": "Crie uma proposta comercial convincente"
        }
        
        template = templates.get(tipo.lower(), "Crie o conteúdo solicitado de forma profissional")
        
        completion = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system", 
                    "content": f"""Você é a Xuxu, especialista em criação de conteúdo profissional.
                    
                    {template}. Use formatação clara com emojis apropriados para tornar o conteúdo mais visual e profissional.
                    
                    Sempre estruture bem o conteúdo com seções claras."""
                },
                {"role": "user", "content": f"Tema: {tema}\n\nDetalhes adicionais: {detalhes}"}
            ],
            temperature=0.7
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Erro ao criar conteúdo: {str(e)}"

async def traduzir_tool(texto: str, idioma_origem: str, idioma_destino: str) -> str:
    """Traduz textos entre idiomas"""
    try:
        completion = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": f"""Você é a Xuxu, especialista em traduções.
                    
                    Traduza o texto de {idioma_origem} para {idioma_destino} mantendo:
                    • O tom e contexto original
                    • Expressões adequadas ao idioma de destino
                    • Formatação original
                    
                    Se houver termos técnicos, explique quando necessário."""
                },
                {"role": "user", "content": texto}
            ],
            temperature=0.3
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Erro ao traduzir: {str(e)}"

async def resolver_problema_tool(problema: str, contexto: str = "") -> str:
    """Ajuda a resolver problemas"""
    try:
        completion = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system", 
                    "content": """Você é a Xuxu, especialista em resolução de problemas.
                    
                    Para cada problema, forneça:
                    
                    🎯 **ANÁLISE DO PROBLEMA**
                    
                    🔍 **Causa Raiz:**
                    • [Identifique as possíveis causas]
                    
                    💡 **Soluções Propostas:**
                    • [Liste soluções práticas em ordem de prioridade]
                    
                    📋 **Plano de Ação:**
                    • [Passos concretos para implementar]
                    
                    ⚠️ **Riscos e Considerações:**
                    • [Pontos importantes a considerar]
                    
                    📈 **Resultados Esperados:**
                    • [O que esperar de cada solução]"""
                },
                {"role": "user", "content": f"Problema: {problema}\n\nContexto: {contexto}"}
            ],
            temperature=0.5
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Erro ao resolver problema: {str(e)}"

# Thread management
async def get_or_create_thread(conversation_id: str) -> str:
    """Recupera ou cria uma thread do OpenAI para a conversa"""
    thread_id = get_thread_id(conversation_id)
    
    if thread_id:
        try:
            await client.beta.threads.retrieve(thread_id)
            return thread_id
        except:
            pass
    
    thread = await client.beta.threads.create()
    save_thread_mapping(conversation_id, thread.id)
    return thread.id

async def handle_tool_calls(run, thread_id: str, user_id: str = ""):
    """Processa chamadas de tools do assistant"""
    if run.required_action and run.required_action.submit_tool_outputs:
        tool_outputs = []
        
        for tool_call in run.required_action.submit_tool_outputs.tool_calls:
            function_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            
            result = "Função não encontrada"
            
            # Tools originais
            if function_name == "resumir_texto":
                result = await resumir_texto_tool(
                    args.get("texto", ""), 
                    args.get("tipo", "geral")
                )
            elif function_name == "analisar_dados":
                result = await analisar_dados_tool(
                    args.get("dados", ""),
                    args.get("tipo_analise", "geral")
                )
            elif function_name == "criar_conteudo":
                result = await criar_conteudo_tool(
                    args.get("tipo", ""),
                    args.get("tema", ""),
                    args.get("detalhes", "")
                )
            elif function_name == "traduzir":
                result = await traduzir_tool(
                    args.get("texto", ""),
                    args.get("idioma_origem", ""),
                    args.get("idioma_destino", "")
                )
            elif function_name == "resolver_problema":
                result = await resolver_problema_tool(
                    args.get("problema", ""),
                    args.get("contexto", "")
                )
            # Tools Microsoft Graph
            elif function_name == "listar_eventos_calendar":
                result = await listar_eventos_calendar_tool(
                    args.get("user_email", ""),
                    args.get("dias", 7)
                )
            elif function_name == "criar_evento_calendar":
                result = await criar_evento_calendar_tool(
                    args.get("user_email", ""),
                    args.get("titulo", ""),
                    args.get("data_inicio", ""),
                    args.get("data_fim", ""),
                    args.get("descricao", ""),
                    args.get("local", "")
                )
            elif function_name == "buscar_usuarios":
                result = await buscar_usuarios_tool(
                    args.get("query", "")
                )
            # Tools Google Calendar
            elif function_name == "listar_eventos_google":
                result = await listar_eventos_google_tool(
                    user_id,
                    args.get("dias", 7)
                )
            elif function_name == "criar_evento_google":
                result = await criar_evento_google_tool(
                    user_id,
                    args.get("titulo", ""),
                    args.get("data_inicio", ""),
                    args.get("data_fim", ""),
                    args.get("descricao", ""),
                    args.get("local", "")
                )
            elif function_name == "listar_eventos_calendar":
                result = await listar_eventos_calendar_tool(
                    args.get("user_email", ""),
                    args.get("dias", 7)
                )
            elif function_name == "criar_evento_calendar":
                result = await criar_evento_calendar_tool(
                    args.get("user_email", ""),
                    args.get("titulo", ""),
                    args.get("data_inicio", ""),
                    args.get("data_fim", ""),
                    args.get("descricao", ""),
                    args.get("local", "")
                )
            elif function_name == "buscar_usuarios":
                result = await buscar_usuarios_tool(
                    args.get("query", "")
                )
            
            # NOVAS FUNÇÕES - Google Calendar
            elif function_name == "listar_eventos_google":
                result = await listar_eventos_google_tool(
                    user_id,  # Passa o user_id para autenticação
                    args.get("dias", 7)
                )
            elif function_name == "criar_evento_google":
                result = await criar_evento_google_tool(
                    user_id,  # Passa o user_id para autenticação
                    args.get("titulo", ""),
                    args.get("data_inicio", ""),
                    args.get("data_fim", ""),
                    args.get("descricao", ""),
                    args.get("local", "")
                )
            tool_outputs.append({
                "tool_call_id": tool_call.id,
                "output": result
            })
        
        if tool_outputs:
            await client.beta.threads.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )

async def call_openai_assistant(conversation_id: str, user_message: str, user_name: str = None, user_id: str = "") -> str:
    """Chama o OpenAI Assistant com gerenciamento de thread"""
    try:
        thread_id = await get_or_create_thread(conversation_id)

        # Adiciona contexto do usuário se disponível
        enhanced_message = user_message
        if user_name:
            enhanced_message = f"[Usuário: {user_name}] {user_message}"

        await client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=enhanced_message
        )

        run = await client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=OPENAI_ASSISTANT_ID
        )

        # Aguarda processamento
        while True:
            run = await client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            
            if run.status == "completed":
                break
            elif run.status == "requires_action":
                await handle_tool_calls(run, thread_id, user_id)
            elif run.status in ["failed", "cancelled", "expired"]:
                return f"🤖 Opa! Encontrei um probleminha técnico (status: {run.status}). Pode tentar novamente?"
            
            await asyncio.sleep(1)

        # Recupera resposta
        messages = await client.beta.threads.messages.list(
            thread_id=thread_id,
            limit=1
        )
        
        if messages.data and messages.data[0].role == "assistant":
            content = messages.data[0].content[0]
            if hasattr(content, 'text'):
                return content.text.value
            else:
                return str(content)
        
        return "🤖 Hmm, algo deu errado na minha resposta. Pode reformular sua pergunta?"

    except Exception as e:
        print(f"Erro no assistant: {e}")
        return f"🤖 Oi! Sou a Xuxu, sua assistente IA! 😊 Encontrei um erro técnico: {str(e)}"

# Bot do Teams
class XuxuTeamsBot:
    async def on_message_activity(self, turn_context: TurnContext):
        """Processa mensagens do usuário"""
        user_message = turn_context.activity.text or ""
        conversation_id = turn_context.activity.conversation.id
        user_name = turn_context.activity.from_property.name if turn_context.activity.from_property else None
        user_id = turn_context.activity.from_property.id if turn_context.activity.from_property else ""
        
        # Comandos especiais
        if user_message.startswith("/auth"):
            await self.handle_auth_command(turn_context, user_message, user_id)
            return
        
        # Salva mensagem do usuário
        save_message(conversation_id, "user", user_message, user_name)
        
        # Processa com o assistant
        assistant_response = await call_openai_assistant(conversation_id, user_message, user_name, user_id)
        
        # Salva resposta do assistant
        save_message(conversation_id, "assistant", assistant_response)
        
        # Envia resposta
        await turn_context.send_activity(assistant_response)

    async def handle_auth_command(self, turn_context: TurnContext, message: str, user_id: str):
        """Processa comandos de autenticação"""
        if "/auth google" in message:
            # URL de autorização Google
            google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={GOOGLE_CLIENT_ID}&redirect_uri={GOOGLE_REDIRECT_URI}&scope=https://www.googleapis.com/auth/calendar&response_type=code&state={user_id}"
            
            await turn_context.send_activity(f"🔐 **Autenticação Google Calendar**\n\nClique no link para autorizar:\n{google_auth_url}")
        
        elif "/auth microsoft" in message:
            # URL de autorização Microsoft
            microsoft_auth_url = f"{AUTHORITY}/oauth2/v2.0/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri={GOOGLE_REDIRECT_URI}&scope={GRAPH_SCOPES}&state={user_id}"
            
            await turn_context.send_activity(f"🔐 **Autenticação Microsoft**\n\nClique no link para autorizar:\n{microsoft_auth_url}")
        
        else:
            await turn_context.send_activity("""🔐 **Comandos de Autenticação:**
            
• `/auth google` - Conectar Google Calendar
• `/auth microsoft` - Conectar Microsoft Graph (Outlook/Teams)

Use esses comandos para conectar seus calendários e aproveitar todas as funcionalidades da Xuxu! 🚀""")

    async def on_members_added_activity(self, members_added, turn_context: TurnContext):
        """Boas-vindas para novos membros"""
        welcome_text = """🤖 Olá! Eu sou a **Xuxu**, sua assistente IA completa! 😊

**💬 CONVERSAÇÃO GERAL:**
• Respondo qualquer pergunta como uma IA avançada
• Explico conceitos, ajudo com decisões, tiro dúvidas

**🛠️ FERRAMENTAS DISPONÍVEIS:**
• 📝 **Resumir** documentos, reuniões, artigos
• 📊 **Analisar** dados e tendências  
• ✍️ **Criar** emails, apresentações, relatórios
• 🌐 **Traduzir** textos entre idiomas
• 🧠 **Resolver** problemas complexos

**📅 INTEGRAÇÕES DE CALENDÁRIO:**
• 🔗 Microsoft Outlook/Teams (Graph API)
• 🔗 Google Calendar
• Listar, criar e gerenciar eventos

**🔐 COMANDOS ESPECIAIS:**
• `/auth google` - Conectar Google Calendar
• `/auth microsoft` - Conectar Microsoft Graph

É só perguntar! Estou aqui para facilitar seu trabalho! ✨"""

        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(welcome_text)

    async def on_turn(self, turn_context: TurnContext):
        """Manipulador principal do bot"""
        if turn_context.activity.type == "message":
            await self.on_message_activity(turn_context)
        elif turn_context.activity.type == "membersAdded":
            await self.on_members_added_activity(
                turn_context.activity.members_added, 
                turn_context
            )

bot = XuxuTeamsBot()

# ----------------------
# Endpoints de Autenticação
# ----------------------

@app.get("/auth/callback")
async def auth_callback(code: str, state: str, req: Request):
    """Callback para autenticação OAuth (Google e Microsoft)"""
    try:
        # Determina se é Google ou Microsoft baseado nos parâmetros
        if "googleapis" in req.headers.get("referer", ""):
            # Google OAuth
            token_url = "https://oauth2.googleapis.com/token"
            data = {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": GOOGLE_REDIRECT_URI
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(token_url, data=data)
                token_data = response.json()
            
            if "access_token" in token_data:
                save_user_token(
                    state,  # user_id
                    "google",
                    token_data["access_token"],
                    token_data.get("refresh_token"),
                    token_data.get("expires_in", 3600)
                )
                return JSONResponse({"message": "✅ Google Calendar conectado com sucesso!"})
        
        else:
            # Microsoft OAuth
            token_url = f"{AUTHORITY}/oauth2/v2.0/token"
            data = {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "scope": GRAPH_SCOPES
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(token_url, data=data)
                token_data = response.json()
            
            if "access_token" in token_data:
                save_user_token(
                    state,  # user_id
                    "microsoft",
                    token_data["access_token"],
                    token_data.get("refresh_token"),
                    token_data.get("expires_in", 3600)
                )
                return JSONResponse({"message": "✅ Microsoft Graph conectado com sucesso!"})
        
        return JSONResponse({"error": "Falha na autenticação"}, status_code=400)
        
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ----------------------
# Endpoints Principais
# ----------------------

@app.post("/api/messages")
async def messages_endpoint(req: Request):
    """Endpoint principal para receber mensagens do Teams"""
    try:
        body = await req.json()
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")

        async def aux_func(turn_context: TurnContext):
            await bot.on_turn(turn_context)

        response = await adapter.process_activity(activity, auth_header, aux_func)
        
        if response:
            return JSONResponse(content=response.body, status_code=response.status)
        return Response(status_code=200)
        
    except Exception as e:
        print(f"Erro ao processar mensagem: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/healthz")
async def health_check():
    """Endpoint de health check"""
    integrations_status = {
        "microsoft_graph": bool(CLIENT_ID and CLIENT_SECRET and TENANT_ID),
        "google_calendar": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        "openai": bool(OPENAI_API_KEY and OPENAI_ASSISTANT_ID)
    }
    
    return {
        "status": "ok", 
        "bot": "Xuxu - Assistente IA Completa + Integrações", 
        "timestamp": datetime.utcnow().isoformat(),
        "integrations": integrations_status,
        "capabilities": [
            "Conversação geral (IA avançada)",
            "Resumir conteúdos", 
            "Análise de dados",
            "Criação de conteúdo",
            "Traduções",
            "Resolução de problemas",
            "Microsoft Graph (Outlook/Teams)",
            "Google Calendar"
        ]
    }

@app.get("/memory/{conversation_id}")
async def get_memory(conversation_id: str, limit: int = 50):
    """Recupera histórico de conversa"""
    try:
        history = get_conversation_history(conversation_id, limit=limit)
        return {
            "conversation_id": conversation_id,
            "messages": [
                {
                    "role": h.role,
                    "content": h.content,
                    "user_name": h.user_name,
                    "timestamp": h.timestamp.isoformat()
                } for h in history
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
async def get_stats():
    """Estatísticas do bot"""
    with Session(engine) as session:
        total_messages = session.exec(select(ConversationMemory)).all()
        total_threads = session.exec(select(ThreadMapping)).all()
        total_tokens = session.exec(select(UserTokens)).all()
        
        user_messages = [m for m in total_messages if m.role == "user"]
        unique_users = len(set(m.user_name for m in user_messages if m.user_name))
        
        google_users = len([t for t in total_tokens if t.provider == "google"])
        microsoft_users = len([t for t in total_tokens if t.provider == "microsoft"])
        
        return {
            "bot_name": "Xuxu",
            "type": "Assistente IA Completa + Integrações",
            "total_messages": len(total_messages),
            "total_conversations": len(total_threads),
            "unique_users": unique_users,
            "integrations": {
                "google_calendar_users": google_users,
                "microsoft_graph_users": microsoft_users
            },
            "capabilities_count": 8
        }

@app.get("/integrations/test")
async def test_integrations():
    """Testa as integrações disponíveis"""
    results = {}
    
    # Teste Microsoft Graph
    if graph_client:
        try:
            # Testa acesso básico
            results["microsoft_graph"] = {
                "status": "✅ Configurado",
                "client_id": CLIENT_ID[:8] + "...",
                "tenant_id": TENANT_ID[:8] + "..."
            }
        except Exception as e:
            results["microsoft_graph"] = {
                "status": "❌ Erro",
                "error": str(e)
            }
    else:
        results["microsoft_graph"] = {
            "status": "⚠️ Não configurado",
            "message": "Configure CLIENT_ID, CLIENT_SECRET e TENANT_ID"
        }
    
    # Teste Google Calendar
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        results["google_calendar"] = {
            "status": "✅ Configurado",
            "client_id": GOOGLE_CLIENT_ID[:20] + "...",
            "redirect_uri": GOOGLE_REDIRECT_URI
        }
    else:
        results["google_calendar"] = {
            "status": "⚠️ Não configurado",
            "message": "Configure GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET"
        }
    
    # Teste OpenAI
    results["openai"] = {
        "status": "✅ Configurado" if OPENAI_API_KEY and OPENAI_ASSISTANT_ID else "⚠️ Incompleto",
        "assistant_id": OPENAI_ASSISTANT_ID[:10] + "..." if OPENAI_ASSISTANT_ID else "Não configurado"
    }
    
    return results

@app.get("/users/{user_id}/tokens")
async def get_user_tokens(user_id: str):
    """Lista tokens de um usuário"""
    with Session(engine) as session:
        statement = select(UserTokens).where(UserTokens.user_id == user_id)
        tokens = session.exec(statement).all()
        
        return {
            "user_id": user_id,
            "tokens": [
                {
                    "provider": t.provider,
                    "expires_at": t.expires_at.isoformat(),
                    "is_valid": t.expires_at > datetime.utcnow()
                } for t in tokens
            ]
        }

if __name__ == "__main__":
    import uvicorn
    
    print("🤖 Iniciando Xuxu - Assistente IA Completa + Integrações...")
    print(f"Assistant ID: {OPENAI_ASSISTANT_ID}")
    print("Capacidades:")
    print("  • Conversação geral (IA avançada)")
    print("  • Resumos, análises, criação de conteúdo")
    print("  • Traduções, resolução de problemas")
    print(f"  • Microsoft Graph: {'✅' if graph_client else '❌'}")
    print(f"  • Google Calendar: {'✅' if GOOGLE_CLIENT_ID else '❌'}")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )