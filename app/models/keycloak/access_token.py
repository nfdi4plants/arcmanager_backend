from __future__ import annotations

from pydantic import BaseModel, Field


class AccessToken(BaseModel):
    access_token: str
    expires_in: int
    refresh_expires_in: int
    refresh_token: str
    token_type: str
    id_token: str
    not_before_policy: int = Field(..., alias='not-before-policy')
    scope: str
    accessTokenExpiration: int
    created_at: int
