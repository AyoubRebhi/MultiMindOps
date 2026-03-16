from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None


class TaskCreate(TaskBase):
    pass


class TaskRead(TaskBase):
    id: int
    completed: bool

    class Config:
        orm_mode = True
