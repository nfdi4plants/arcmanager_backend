from __future__ import annotations

from typing import List, Optional, Union

from pydantic import BaseModel, Field


class Value(BaseModel):
    annotationValue: str
    termSource: str
    termAccession: str


class HeaderItem(BaseModel):
    headertype: str
    values: List[Union[str, Value]]


class Value2(BaseModel):
    annotationValue: str
    termSource: str
    termAccession: str


class Value1(BaseModel):
    celltype: str
    values: List[Union[str, Value2, dict]]


class Table(BaseModel):
    name: str
    header: List[HeaderItem]
    values: Optional[List[List[Union[List[int], Value1]]]] = []


class Author(BaseModel):
    firstName: str = Field(examples=["Dominik, Hajira"])
    lastName: str = Field(examples=["Brilhaus, Jabeen"])
    email: Optional[str] = None


class Tag(BaseModel):
    annotationValue: str
    termSource: Optional[str] = None
    termAccession: Optional[str] = None


class Template(BaseModel):
    id: str = Field(examples=["52953c18-2f3e-41e4-9b64-e4b39a6f4685"])
    table: Table
    name: str = Field(examples=["RNA extraction"])
    description: str = Field(examples=["Template to describe the extraction of RNA."])
    organisation: str = Field(examples=["DataPLANT"])
    version: str = Field(examples=["1.2.0"])
    authors: List[Author]
    endpoint_repositories: Optional[List]
    tags: Optional[List[Tag]]
    last_updated: str = Field(examples=["2024-02-02T23:38:44.0000000"])


class Templates(BaseModel):
    templates: List[Template]
