from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class ColumnHeader(BaseModel):
    Type: str
    Name: str
    isSingleColumn: bool
    isInputColumn: bool
    isOutputColumn: bool
    isFeaturedColumn: bool
    isTermColumn: bool


class ColumnTerm(BaseModel):
    Name: str
    TermAccession: str
    toNumberFormat: str
    accessionToTSR: str
    accessionToTAN: str


class UnitTermItem(BaseModel):
    Name: str
    TermAccession: str
    toNumberFormat: str
    accessionToTSR: str
    accessionToTAN: str


class BuildingBlocks(BaseModel):
    ColumnHeader: ColumnHeader
    ColumnTerm: ColumnTerm
    UnitTerm: Optional[UnitTermItem]
    Rows: List
    HasUnit: bool
    HasExistingTerm: bool
    HasCompleteTerm: bool
    HasValues: bool


class TemplateBB(BaseModel):
    templateBB: List[BuildingBlocks]
