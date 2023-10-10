from __future__ import annotations

from typing import List

from pydantic import BaseModel


class Entry(BaseModel):
    id: str
    name: str
    type: str
    path: str
    mode: str


class Arc(BaseModel):
    Arc: List[Entry]
