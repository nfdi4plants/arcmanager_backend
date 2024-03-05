from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class User(BaseModel):
    id: int = Field(examples=[137])
    username: str = Field(examples=["lu98be"])
    name: str = Field(examples=["Your Name"])
    state: str = Field(examples=["active"])
    avatar_url: Optional[str]
    web_url: str = Field(examples=["https://gitlab.nfdi4plants.de/lu98be"])


class Users(BaseModel):
    users: List[User]
