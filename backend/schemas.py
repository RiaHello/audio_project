from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class SuccessEnvelope(BaseModel, Generic[T]):
    request_id: str
    data: T


class HealthData(BaseModel):
    status: str = Field(examples=["ok"])


class UploadData(BaseModel):
    audio_id: str


class AsrRequest(BaseModel):
    audio_id: str = Field(min_length=1)


class AsrData(BaseModel):
    text: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    stage: str


class ErrorEnvelope(BaseModel):
    request_id: str
    error: ErrorDetail
