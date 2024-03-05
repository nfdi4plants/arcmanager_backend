from __future__ import annotations

from typing import List

from pydantic import BaseModel


class Term(BaseModel):
    Accession: str
    Name: str
    Description: str
    IsObsolete: bool
    FK_Ontology: str


class Terms(BaseModel):
    terms: List[Term]
