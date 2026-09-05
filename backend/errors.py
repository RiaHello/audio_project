from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, stage: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.stage = stage


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def error_body(request: Request, code: str, message: str, stage: str) -> dict:
    return {
        "request_id": request_id_of(request),
        "error": {
            "code": code,
            "message": message,
            "stage": stage,
        },
    }


def error_response(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(request, exc.code, exc.message, exc.stage),
    )


def stage_from_path(path: str) -> str:
    name = path.strip("/").split("/", 1)[0]
    return name or "unknown"
