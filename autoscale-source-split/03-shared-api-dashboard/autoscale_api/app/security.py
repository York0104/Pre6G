import os
import secrets
from typing import Optional

from fastapi import Request
from starlette.responses import JSONResponse


def get_configured_api_token() -> str:
    return os.getenv("AUTOSCALE_API_TOKEN", "").strip()


def is_auth_enabled() -> bool:
    return bool(get_configured_api_token())


def extract_request_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    api_token = request.headers.get("x-api-token", "").strip()
    if api_token:
        return api_token

    return None


def is_exempt_path(path: str) -> bool:
    if path in {"/", "/docs", "/redoc", "/openapi.json"}:
        return True
    return path.startswith("/docs/") or path.startswith("/redoc/")


async def token_auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS" or is_exempt_path(request.url.path) or not is_auth_enabled():
        return await call_next(request)

    expected_token = get_configured_api_token()
    provided_token = extract_request_token(request)

    if not provided_token or not secrets.compare_digest(provided_token, expected_token):
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Unauthorized",
                "message": "Provide a valid Bearer token or X-API-Token header.",
            },
        )

    return await call_next(request)
