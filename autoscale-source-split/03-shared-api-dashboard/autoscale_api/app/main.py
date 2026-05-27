from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.full_metrics import router as full_metrics_router
from app.routers.experiments import router as experiments_router
from app.routers.nodes import router as nodes_router
from app.security import token_auth_middleware

app = FastAPI(title="Pre6G AutoScale API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://140.113.179.9:5173",
        "http://140.113.179.9:5174",
    ],
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
