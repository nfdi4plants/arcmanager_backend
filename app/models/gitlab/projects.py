from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class Namespace(BaseModel):
    id: int = Field(examples=[310])
    name: str = Field(examples=["Your Name"])
    path: str = Field(examples=["nickname"])
    kind: str = Field(examples=["user"])
    full_path: str = Field(examples=["nickname"])
    parent_id: Any
    avatar_url: Optional[str]
    web_url: str = Field(examples=["https://gitlab.nfdi4plants.de/nickname"])


class Project(BaseModel):
    id: int = Field(examples=[230])
    description: Optional[str] = Field(examples=["this is a description"])
    name: str = Field(examples=["ArcName"])
    name_with_namespace: str = Field(examples=["your name/ArcName"])
    path: str = Field(examples=["ArcName"])
    path_with_namespace: str = Field(examples=["nickname/ArcName"])
    created_at: str = Field(examples=["1970-01-01T12:34:56.109Z"])
    default_branch: str = Field(examples=["main"], default="main")
    tag_list: Optional[List] = Field(examples=[["ARC", "RNA"]])
    topics: List = Field(examples=[["ARC", "RNA"]])
    ssh_url_to_repo: str = Field(
        examples=["ssh://git@gitlab.nfdi4plants.de/nickname/ArcName.git"]
    )
    http_url_to_repo: str = Field(
        examples=["https://gitlab.nfdi4plants.de/nickname/ArcName.git"]
    )
    web_url: str = Field(examples=["https://gitlab.nfdi4plants.de/nickname/ArcName"])
    readme_url: Optional[str] = Field(
        examples=[
            "https://gitlab.nfdi4plants.de/nickname/ArcName/~/blob/main/README.md"
        ],
        default="",
    )
    avatar_url: Optional[str] = Field(
        examples=[
            "https://gitlab.nfdi4plants.de/uploads/~/system/project/avatar/230/avatarName.jpg"
        ]
    )
    forks_count: Optional[int] = Field(examples=[3], default=0)
    star_count: Optional[int] = Field(examples=[2])
    last_activity_at: str = Field(examples=["2024-01-01T12:34:56.373Z"])
    namespace: Namespace


class Projects(BaseModel):
    projects: List[Project]
