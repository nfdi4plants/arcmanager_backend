from __future__ import annotations

from pydantic import BaseModel


class Commit(BaseModel):
    file_path: str
    branch: str
