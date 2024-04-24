from __future__ import annotations

from pydantic import BaseModel, Field


class FileContent(BaseModel):
    file_name: str = Field(examples=["README.md"])
    file_path: str = Field(examples=["README.md"])
    size: int = Field(examples=[1234])
    encoding: str = Field(examples=["base64"])
    content_sha256: str = Field(examples=["4a0a978e478a50feccd9ab38572b1..."])
    ref: str = Field(examples=["main"])
    blob_id: str = Field(examples=["12aba94a8e7fff02340..."])
    commit_id: str = Field(examples=["84d5ebb0ca5b05fe..."])
    last_commit_id: str = Field(examples=["2790b185de2f32930ade..."])
    execute_filemode: bool = Field(examples=[False])
    content: str = Field(examples=["IyB0ZXN0YXJjCgo8ZG....bnRhaW5lcnMuCg=="])
