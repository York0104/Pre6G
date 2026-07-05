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
    if path in {"/", "/docs", "/redoc", "/openapi.json", "/metrics"}:
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


PLACEHOLDER_TOKENS = {
    "replace-with-a-long-random-token",
    "replace-with-issued-token",
}

REQUIRED_ENDPOINT_ENV_VARS = (
    "VM_URL",
    "NETDATA_URL",
    "NETDATA_CHILD_URL",
    "NETDATA_PARENT_BASE_URL",
    "KSM_URL",
)


def _is_placeholder_value(value: str) -> bool:
    normalized = (value or "").strip()
    if not normalized:
        return False
    if normalized in PLACEHOLDER_TOKENS:
        return True
    return "<control-plane-ip>" in normalized.lower() or "<control_plane_ip>" in normalized.lower()


def validate_runtime_configuration() -> None:
    token = get_configured_api_token()
    if _is_placeholder_value(token):
        raise RuntimeError(
            "AUTOSCALE_API_TOKEN is still a placeholder. "
            "Replace it in autoscale-api.env before starting autoscale_api."
        )

    bad_keys = []
    for key in REQUIRED_ENDPOINT_ENV_VARS:
        value = os.getenv(key, "").strip()
        if _is_placeholder_value(value):
            bad_keys.append(key)

    if bad_keys:
        joined = ", ".join(bad_keys)
        raise RuntimeError(
            f"autoscale_api runtime env still contains placeholder values for: {joined}. "
            "Replace <control-plane-ip> with the real host-side endpoints before starting the service."
        )
