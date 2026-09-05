import uuid
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from api.routes import router
from config import settings
from errors import AppError, error_body, error_response, stage_from_path

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app = FastAPI(title="语音约碰面地点", version="0.1.0")
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(request, exc)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    stage = stage_from_path(request.url.path)
    messages = {
        "upload": "请求缺少 file 或字段类型不正确。",
        "asr": "请求缺少 audio_id 或字段类型不正确。",
    }
    return JSONResponse(
        status_code=422,
        content=error_body(
            request,
            "VALIDATION_ERROR",
            messages.get(stage, "请求缺少字段或字段类型不正确。"),
            stage,
        ),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, AppError):
        return error_response(request, exc)
    logger.exception("unhandled error path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_body(
            request,
            "INTERNAL_ERROR",
            "服务暂时不可用，请稍后重试。",
            stage_from_path(request.url.path),
        ),
    )
