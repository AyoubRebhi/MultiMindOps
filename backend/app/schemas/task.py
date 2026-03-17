from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class TaskCreate(BaseModel):
    prompt: str


class TaskResponse(BaseModel):
    id: str
    prompt: str
    status: str
    plan: Optional[Any] = None
    logs: List[Any] = []
    result: Optional[Any] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True