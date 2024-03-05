from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class Entry(BaseModel):
    id: str = Field(examples=["482807e41cd1b6b..."])
    name: str = Field(examples=["assays"])
    type: str = Field(examples=["tree"])
    path: str = Field(examples=["assays"])
    mode: str = Field(examples=["040000"])


class Arc(BaseModel):
    Arc: List[Entry]
