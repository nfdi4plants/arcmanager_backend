from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


class LFSUpload(str, Enum):
    true = "true"
    false = "false"


class isaContent(BaseModel):
    isaInput: list = Field(examples=[["Investigation Title", "testArc"]])
    isaPath: str = Field(examples=["isa.investigation.xlsx"])
    isaRepo: int = Field(examples=[230], ge=1)
    arcBranch: str = Field(examples=["main"])
    multiple: bool = Field(default=False)


class arcContent(BaseModel):
    name: str = Field(examples=["New Arc"])
    description: str = Field(examples=["This is a description for the new Arc"])
    investIdentifier: str = Field(examples=["newArc123"])
    groupId: Optional[int] = Field(examples=[407], default=None, ge=1)


class newIsa(BaseModel):
    identifier: str = Field(examples=["assay1"])
    id: int = Field(examples=[230], ge=1)
    type: Literal["assays", "studies"]
    branch: str = Field(examples=["main"])


class sheetContent(BaseModel):
    tableHead: list[dict] = Field(
        examples=[
            [
                {"Type": "Input [Source Name]"},
                {"Type": "Characteristic [organism]", "Accession": "OBI:0100026"},
            ]
        ]
    )
    tableContent: list[list] = Field(examples=[[[""], ["Apple stem pitting virus"]]])
    path: str = Field(examples=["assays/assay1/isa.assay.xlsx"])
    id: int = Field(examples=[230], ge=1)
    name: str = Field(examples=["Strain"])
    branch: str = Field(examples=["main"])


class syncAssayContent(BaseModel):
    id: int = Field(examples=[230], ge=1)
    pathToStudy: str = Field(examples=["studies/study1/isa.study.xlsx"])
    pathToAssay: str = Field(examples=["assays/assay1/isa.assay.xlsx"])
    assayName: str = Field(examples=["assay1"])
    branch: str = Field(examples=["main"])


class syncStudyContent(BaseModel):
    id: int = Field(examples=[230], ge=1)
    pathToStudy: str = Field(examples=["studies/study1/isa.study.xlsx"])
    studyName: str = Field(examples=["study1"])
    branch: str = Field(examples=["main"])


class folderContent(BaseModel):
    identifier: str = Field(examples=["newFolder"])
    id: int = Field(examples=[230], ge=1)
    path: str = Field(examples=["assays/assay1/dataset"])
    branch: str = Field(examples=["main"])


class userContent(BaseModel):
    userId: int = Field(examples=[137], ge=1)
    username: str = Field(examples=["lu98be"])
    id: int = Field(examples=[230], ge=1)
    role: int = Field(examples=[30], ge=10, le=50, multiple_of=10)


class templateContent(BaseModel):
    table: list
    name: str
    identifier: str
    description: str
    organisation: str
    version: str
    username: dict
    tags: list


class datamapContent(BaseModel):
    id: int = Field(examples=[230], ge=1)
    path: str = Field(examples=["assays/assay1/dataset"])
    branch: str = Field(examples=["main"])
