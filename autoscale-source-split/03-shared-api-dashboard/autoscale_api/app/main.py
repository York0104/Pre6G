import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.full_metrics import router as full_metrics_router
from app.routers.experiments import router as experiments_router
from app.routers.nodes import router as nodes_router
from app.security import token_auth_middleware, validate_runtime_configuration


def _build_allowed_origins() -> list[str]:
    defaults = [
        "http://localhost:4173",
        "http://localhost:4174",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:4173",
        "http://127.0.0.1:4174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://140.113.179.9:4173",
        "http://140.113.179.9:4174",
        "http://140.113.179.9:5173",
        "http://140.113.179.9:5174",
    ]

    extra_origins = [
        origin.strip()
        for origin in os.getenv("AUTOSCALE_API_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]

    return list(dict.fromkeys([*defaults, *extra_origins]))

app = FastAPI(title="Pre6G AutoScale API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(token_auth_middleware)

app.include_router(nodes_router)
app.include_router(full_metrics_router)
app.include_router(experiments_router)


@app.get("/")
def root():
    return {"message": "Pre6G AutoScale API is running"}


@app.on_event("startup")
def validate_config_on_startup():
    validate_runtime_configuration()
