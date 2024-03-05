from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class Template(BaseModel):
    Id: str = Field(examples=["52953c18-2f3e-41e4-9b64-e4b39a6f4685"])
    Name: str = Field(examples=["RNA extraction"])
    Description: str = Field(examples=["Template to describe the extraction of RNA."])
    Organisation: str = Field(examples=["DataPLANT"])
    Version: str = Field(examples=["1.2.0"])
    Authors: str = Field(examples=["Hajira Jabeen, Dominik Brilhaus"])
    Er_Tags: List[str] = Field(
        examples=[["extraction", "RNA", "RNA extraction protocol"]]
    )
    Tags: List[str] = Field(examples=[["extraction", "RNA", "RNA extraction protocol"]])
    TemplateBuildingBlocks: List
    LastUpdated: str = Field(examples=["2024-02-02T23:38:44.0000000"])
    Used: int = Field(examples=[2])
    Rating: int = Field(examples=[0])


class Templates(BaseModel):
    templates: List[Template]
