from __future__ import annotations

from typing import List

from pydantic import BaseModel


class Template(BaseModel):
    Id: str
    Name: str
    Description: str
    Organisation: str
    Version: str
    Authors: str
    Er_Tags: List[str]
    Tags: List[str]
    TemplateBuildingBlocks: List
    LastUpdated: str
    Used: int
    Rating: int


class Templates(BaseModel):
    templates: List[Template]
