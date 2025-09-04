# schemas.py
from pydantic import BaseModel
from typing import Optional

class EventCreate(BaseModel):
    titulo: str
    data_inicio: str
    data_fim: str
    descricao: Optional[str] = None
    local: Optional[str] = None

class AssistantRequest(BaseModel):
    user_id: str
    mensagem: str
