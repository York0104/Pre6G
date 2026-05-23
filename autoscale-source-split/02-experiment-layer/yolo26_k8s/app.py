import io
import os
import time
from datetime import datetime

import torch
from fastapi import FastAPI, File, Query, UploadFile
from PIL import Image
from ultralytics import YOLO

MODEL_NAME = os.getenv("YOLO26_MODEL", "yolo26m.pt")
DEVICE = os.getenv("YOLO26_DEVICE", "cuda:0")
IMGSZ = int(os.getenv("YOLO26_IMGSZ", "640"))
POD_NAME = os.getenv("POD_NAME", os.getenv("HOSTNAME", "unknown"))
NODE_NAME = os.getenv("NODE_NAME", "unknown")
SERVICE_ROLE = os.getenv("YOLO26_SERVICE_ROLE", "unknown")

app = FastAPI(title="YOLO26 K8s Service")

model = YOLO(MODEL_NAME)


@app.on_event("startup")
def warmup():
    dummy = Image.new("RGB", (IMGSZ, IMGSZ), color=(0, 0, 0))
    try:
        model.predict(dummy, device=DEVICE, imgsz=IMGSZ, verbose=False)
    except Exception as e:
        print(f"[startup warmup] warning: {e}")


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "time": datetime.now().isoformat(timespec="seconds"),
        "model": MODEL_NAME,
        "device": DEVICE,
        "imgsz": IMGSZ,
        "pod_name": POD_NAME,
        "node_name": NODE_NAME,
        "service_role": SERVICE_ROLE,
    }


@app.post("/infer")
async def infer(
    file: UploadFile = File(...),
    repeat: int = Query(1, ge=1, le=200),
):
    handler_t0 = time.perf_counter()
    raw = await file.read()
    img = Image.open(io.BytesIO(raw)).convert("RGB")

    repeat = max(1, min(int(repeat), 200))

    t0 = time.perf_counter()
    last_results = None
    for _ in range(repeat):
        last_results = model.predict(
            img,
            device=DEVICE,
            imgsz=IMGSZ,
            verbose=False,
        )

    if torch.cuda.is_available():
        torch.cuda.synchronize()

    server_latency_ms = (time.perf_counter() - t0) * 1000.0
    results = last_results

    num_boxes = 0
    if results and len(results) > 0 and getattr(results[0], "boxes", None) is not None:
        num_boxes = len(results[0].boxes)

    server_total_latency_ms = (time.perf_counter() - handler_t0) * 1000.0

    return {
        "ok": True,
        "server_time": datetime.now().isoformat(timespec="milliseconds"),
        "server_latency_ms": round(server_latency_ms, 3),
        "server_total_latency_ms": round(server_total_latency_ms, 3),
        "repeat": repeat,
        "num_boxes": int(num_boxes),
        "model": MODEL_NAME,
        "device": DEVICE,
        "imgsz": IMGSZ,
        "pod_name": POD_NAME,
        "node_name": NODE_NAME,
        "service_role": SERVICE_ROLE,
        "filename": file.filename,
    }
