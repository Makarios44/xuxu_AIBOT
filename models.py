from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime

class UserTokens(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    provider: str  # "google" ou "microsoft"
    access_token: str
    refresh_token: str
    expires_at: Optional[float] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ConversationMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: str = Field(index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)