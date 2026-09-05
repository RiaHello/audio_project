from fastapi import APIRouter, File, Request, UploadFile

from schemas import (
    AsrData,
    AsrRequest,
    ExtractData,
    ExtractRequest,
    HealthData,
    SuccessEnvelope,
    UploadData,
)
from services.asr import transcribe_audio
from services.extract import extract_meetup
from services.upload_audio import store_uploaded_audio

router = APIRouter()


@router.get("/health", response_model=SuccessEnvelope[HealthData])
async def health(request: Request) -> SuccessEnvelope[HealthData]:
    return SuccessEnvelope(
        request_id=request.state.request_id,
        data=HealthData(status="ok"),
    )


@router.post("/upload", response_model=SuccessEnvelope[UploadData])
async def upload(
    request: Request,
    file: UploadFile = File(...),
) -> SuccessEnvelope[UploadData]:
    audio_id = await store_uploaded_audio(file)
    return SuccessEnvelope(
        request_id=request.state.request_id,
        data=UploadData(audio_id=audio_id),
    )


@router.post("/asr", response_model=SuccessEnvelope[AsrData])
async def asr(request: Request, body: AsrRequest) -> SuccessEnvelope[AsrData]:
    text = await transcribe_audio(body.audio_id)
    return SuccessEnvelope(
        request_id=request.state.request_id,
        data=AsrData(text=text),
    )


@router.post("/extract", response_model=SuccessEnvelope[ExtractData])
async def extract(
    request: Request,
    body: ExtractRequest,
) -> SuccessEnvelope[ExtractData]:
    result = await extract_meetup(body.text, body.city)
    return SuccessEnvelope(
        request_id=request.state.request_id,
        data=ExtractData(
            city_a=result.city_a,
            address_a=result.address_a,
            city_b=result.city_b,
            address_b=result.address_b,
            category=result.category,
        ),
    )
