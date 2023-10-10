from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, RootModel


class Namespace(BaseModel):
    id: int
    name: str
    path: str
    kind: str
    full_path: str
    parent_id: Any
    avatar_url: Optional[str]
    web_url: str


class Project(BaseModel):
    id: int
    description: Optional[str]
    name: str
    name_with_namespace: str
    path: str
    path_with_namespace: str
    created_at: str
    default_branch: str
    tag_list: List
    topics: List
    ssh_url_to_repo: str
    http_url_to_repo: str
    web_url: str
    readme_url: Optional[str]
    avatar_url: Optional[str]
    forks_count: int
    star_count: int
    last_activity_at: str
    namespace: Namespace


class Projects(BaseModel):
    projects: List[Project]
