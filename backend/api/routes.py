from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse

from schemas import (
    AsrData,
    AsrRequest,
    ExtractData,
    ExtractRequest,
    FinalizeData,
    FinalizeRequest,
    HealthData,
    Midpoint,
    PoiItem,
    SearchData,
    SearchRequest,
    SuccessEnvelope,
    UploadData,
)
from services.asr import transcribe_audio
from services.extract import extract_meetup
from services.finalize import finalize_meetup
from services.search import search_meetup
from services.storage import load_playable_audio
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


@router.post("/search", response_model=SuccessEnvelope[SearchData])
async def search(
    request: Request,
    body: SearchRequest,
) -> SuccessEnvelope[SearchData]:
    result = await search_meetup(
        body.city_a,
        body.address_a,
        body.city_b,
        body.address_b,
        body.category,
    )
    return SuccessEnvelope(
        request_id=request.state.request_id,
        data=SearchData(
            search_id=result.search_id,
            midpoint=Midpoint(
                longitude=result.longitude,
                latitude=result.latitude,
            ),
            pois=[
                PoiItem(
                    name=poi.name,
                    address=poi.address,
                    distance_to_midpoint_m=poi.distance_to_midpoint_m,
                )
                for poi in result.pois
            ],
        ),
    )


@router.post("/finalize", response_model=SuccessEnvelope[FinalizeData])
async def finalize(
    request: Request,
    body: FinalizeRequest,
) -> SuccessEnvelope[FinalizeData]:
    result = await finalize_meetup(body.search_id)
    return SuccessEnvelope(
        request_id=request.state.request_id,
        data=FinalizeData(
            reply_text=result.reply_text,
            audio_url=result.audio_url,
            warning=result.warning,
        ),
    )


@router.get("/audio/{audio_id}")
async def get_audio(audio_id: str) -> FileResponse:
    path, content_type = load_playable_audio(audio_id, stage="audio")
    return FileResponse(path, media_type=content_type)
