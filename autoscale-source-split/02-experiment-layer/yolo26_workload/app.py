import io
import os
import time
from datetime import datetime

import torch
from fastapi import FastAPI, File, Query, UploadFile
from PIL import Image
from starlette.concurrency import run_in_threadpool
from ultralytics import YOLO

MODEL_NAME = os.getenv("YOLO26_MODEL", "yolo26m.pt")
DEVICE = os.getenv("YOLO26_DEVICE", "cuda:0")
IMGSZ = int(os.getenv("YOLO26_IMGSZ", "640"))
WARMUP_BATCH = int(os.getenv("YOLO26_WARMUP_BATCH", "1"))
POD_NAME = os.getenv("POD_NAME", os.getenv("HOSTNAME", "unknown"))
NODE_NAME = os.getenv("NODE_NAME", "unknown")
SERVICE_ROLE = os.getenv("YOLO26_SERVICE_ROLE", "unknown")

app = FastAPI(title="YOLO26 K8s Service")

model = YOLO(MODEL_NAME)


def _clone_images_for_batch(img: Image.Image, batch: int):
    if batch <= 1:
        return img
    return [img.copy() for _ in range(batch)]


def _predict_batch(img: Image.Image, repeat: int, batch: int):
    batched_input = _clone_images_for_batch(img, batch)
    last_results = None

    with torch.inference_mode():
        for _ in range(repeat):
            last_results = model.predict(
                batched_input,
                device=DEVICE,
                imgsz=IMGSZ,
                batch=batch,
                verbose=False,
            )

    if torch.cuda.is_available():
        torch.cuda.synchronize()
    return last_results


@app.on_event("startup")
def warmup():
    dummy = Image.new("RGB", (IMGSZ, IMGSZ), color=(0, 0, 0))
    try:
        _predict_batch(dummy, repeat=1, batch=max(1, WARMUP_BATCH))
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
    batch: int = Query(1, ge=1, le=64),
):
    handler_t0 = time.perf_counter()
    raw = await file.read()
    img = Image.open(io.BytesIO(raw)).convert("RGB")

    repeat = max(1, min(int(repeat), 200))
    batch = max(1, min(int(batch), 64))

    t0 = time.perf_counter()
    results = await run_in_threadpool(_predict_batch, img, repeat, batch)

    server_latency_ms = (time.perf_counter() - t0) * 1000.0

    num_boxes = 0
    total_results = len(results) if results else 0
    if results:
        for item in results:
            boxes = getattr(item, "boxes", None)
            if boxes is not None:
                num_boxes += len(boxes)

    server_total_latency_ms = (time.perf_counter() - handler_t0) * 1000.0

    return {
        "ok": True,
        "server_time": datetime.now().isoformat(timespec="milliseconds"),
        "server_latency_ms": round(server_latency_ms, 3),
        "server_total_latency_ms": round(server_total_latency_ms, 3),
        "repeat": repeat,
        "batch": batch,
        "result_count": total_results,
        "num_boxes": int(num_boxes),
        "model": MODEL_NAME,
        "device": DEVICE,
        "imgsz": IMGSZ,
        "pod_name": POD_NAME,
        "node_name": NODE_NAME,
        "service_role": SERVICE_ROLE,
        "filename": file.filename,
    }
