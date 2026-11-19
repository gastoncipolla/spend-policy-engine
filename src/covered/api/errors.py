"""Error envelope: every error is `{"error": code, "message": message}` (SPEC §7)."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from covered.domain.errors import CoveredError

STATUS_BY_CODE = {
    "validation_error": 422,
    "not_found": 404,
    "unauthenticated": 401,
    "forbidden": 403,
}
"""Every other domain error code is a conflict with the current state (409)."""


def error_response(
    status_code: int, code: str, message: str, **extra: str
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": code, "message": message, **extra}
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(CoveredError)
    async def _domain_error(request: Request, exc: CoveredError) -> JSONResponse:
        response = error_response(
            STATUS_BY_CODE.get(exc.code, 409), exc.code, exc.message
        )
        if exc.code == "unauthenticated":
            response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError | ValidationError
    ) -> JSONResponse:
        return error_response(422, "validation_error", _describe(exc.errors()))

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return error_response(exc.status_code, code, str(exc.detail))


def _describe(errors) -> str:
    parts = []
    for error in errors:
        location = ".".join(str(part) for part in error.get("loc", ()))
        parts.append(f"{location}: {error['msg']}" if location else error["msg"])
    return "; ".join(parts)
