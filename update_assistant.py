# update_assistant.py
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Configuração
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY não configurada")
if not OPENAI_ASSISTANT_ID:
    raise ValueError("OPENAI_ASSISTANT_ID não configurada")

client = OpenAI(api_key=OPENAI_API_KEY)

# Definições das functions
tools = [
    {
        "type": "function",
        "function": {
            "name": "resumir_texto",
            "description": "Resume qualquer tipo de texto (documentos, reuniões, artigos, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "texto": {"type": "string", "description": "Texto completo para resumir"},
                    "tipo": {"type": "string", "description": "Tipo de resumo: 'geral', 'reuniao', 'tecnico', etc."}
                },
                "required": ["texto"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analisar_dados",
            "description": "Analisa dados, números, métricas e identifica tendências",
            "parameters": {
                "type": "object",
                "properties": {
                    "dados": {"type": "string", "description": "Dados para análise"},
                    "tipo_analise": {"type": "string", "description": "Tipo de análise: 'geral', 'financeira', 'metricas', 'tendencias'"}
                },
                "required": ["dados"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "criar_conteudo",
            "description": "Cria diferentes tipos de conteúdo profissional",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "description": "Tipo de conteúdo: 'email', 'apresentacao', 'documento', 'relatorio', 'ata', 'proposta'"},
                    "tema": {"type": "string", "description": "Tema principal do conteúdo"},
                    "detalhes": {"type": "string", "description": "Detalhes adicionais ou requisitos específicos"}
                },
                "required": ["tipo", "tema"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "traduzir",
            "description": "Traduz textos entre diferentes idiomas",
            "parameters": {
                "type": "object",
                "properties": {
                    "texto": {"type": "string", "description": "Texto para traduzir"},
                    "idioma_origem": {"type": "string", "description": "Idioma de origem (ex: 'portugues', 'ingles', 'espanhol')"},
                    "idioma_destino": {"type": "string", "description": "Idioma de destino (ex: 'ingles', 'portugues', 'frances')"}
                },
                "required": ["texto", "idioma_origem", "idioma_destino"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resolver_problema",
            "description": "Ajuda a resolver problemas complexos com análise estruturada",
            "parameters": {
                "type": "object",
                "properties": {
                    "problema": {"type": "string", "description": "Descrição do problema a ser resolvido"},
                    "contexto": {"type": "string", "description": "Contexto adicional ou informações relevantes"}
                },
                "required": ["problema"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "listar_eventos_calendar",
            "description": "Lista eventos do calendário Microsoft Outlook via Graph API",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_email": {"type": "string", "description": "Email do usuário"},
                    "dias": {"type": "integer", "description": "Número de dias à frente (padrão: 7)"}
                },
                "required": ["user_email"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "criar_evento_calendar",
            "description": "Cria evento no calendário Microsoft Outlook",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_email": {"type": "string", "description": "Email do usuário"},
                    "titulo": {"type": "string", "description": "Título do evento"},
                    "data_inicio": {"type": "string", "description": "Data/hora início (ISO format)"},
                    "data_fim": {"type": "string", "description": "Data/hora fim (ISO format)"},
                    "descricao": {"type": "string", "description": "Descrição do evento"},
                    "local": {"type": "string", "description": "Local do evento"}
                },
                "required": ["user_email", "titulo", "data_inicio", "data_fim"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_usuarios",
            "description": "Busca usuários no Azure Active Directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Nome ou email para buscar"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "listar_eventos_google",
            "description": "Lista eventos do Google Calendar do usuário",
            "parameters": {
                "type": "object",
                "properties": {
                    "dias": {"type": "integer", "description": "Número de dias à frente (padrão: 7)"}
                }
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
                    "titulo": {"type": "string", "description": "Título do evento"},
                    "data_inicio": {"type": "string", "description": "Data/hora início (ISO format)"},
                    "data_fim": {"type": "string", "description": "Data/hora fim (ISO format)"},
                    "descricao": {"type": "string", "description": "Descrição do evento"},
                    "local": {"type": "string", "description": "Local do evento"}
                },
                "required": ["titulo", "data_inicio", "data_fim"]
            }
        }
    }
]

def update_assistant():
    """Atualiza o assistant com as novas functions"""
    try:
        # Recupera o assistant atual
        assistant = client.beta.assistants.retrieve(OPENAI_ASSISTANT_ID)
        print(f"Assistant atual: {assistant.name}")
        
        # Atualiza o assistant com as novas tools
        updated_assistant = client.beta.assistants.update(
            assistant.id,
            tools=tools,
            model="gpt-4-1106-preview"  # Ou o modelo que você está usando
        )
        
        print("✅ Assistant atualizado com sucesso!")
        print(f"Total de functions: {len(updated_assistant.tools)}")
        
        # Lista todas as functions
        for i, tool in enumerate(updated_assistant.tools, 1):
            if tool.type == "function":
                print(f"{i}. {tool.function.name}")
                
    except Exception as e:
        print(f"❌ Erro ao atualizar assistant: {e}")

if __name__ == "__main__":
    update_assistant()