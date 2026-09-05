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


class ExtractRequest(BaseModel):
    text: str = Field(min_length=1)
    city: str = Field(min_length=1)


class ExtractData(BaseModel):
    city_a: str
    address_a: str
    city_b: str
    address_b: str
    category: str


class SearchRequest(BaseModel):
    city_a: str = Field(min_length=1)
    address_a: str = Field(min_length=1)
    city_b: str = Field(min_length=1)
    address_b: str = Field(min_length=1)
    category: str = Field(min_length=1)


class Midpoint(BaseModel):
    longitude: float
    latitude: float


class PoiItem(BaseModel):
    name: str
    address: str
    distance_to_midpoint_m: float


class SearchData(BaseModel):
    search_id: str
    midpoint: Midpoint
    pois: list[PoiItem]


class FinalizeRequest(BaseModel):
    search_id: str = Field(min_length=1)


class FinalizeData(BaseModel):
    reply_text: str
    audio_url: str | None
    warning: str | None


class ErrorDetail(BaseModel):
    code: str
    message: str
    stage: str


class ErrorEnvelope(BaseModel):
    request_id: str
    error: ErrorDetail
