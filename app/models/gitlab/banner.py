from __future__ import annotations

from typing import List

from pydantic import BaseModel


class Banner(BaseModel):
    id: int
    message: str
    starts_at: str
    ends_at: str
    color: str
    font: str
    target_access_levels: List
    target_path: str
    broadcast_type: str
    dismissable: bool
    active: bool


class Banners(BaseModel):
    banners: List[Banner]
