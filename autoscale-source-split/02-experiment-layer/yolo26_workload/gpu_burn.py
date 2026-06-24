import json
import os
import time
from datetime import datetime, timezone

import torch
from PIL import Image
from ultralytics import YOLO


MODEL_NAME = os.getenv("YOLO26_MODEL", "yolo26m.pt")
DEVICE = os.getenv("YOLO26_DEVICE", "cuda:0")
IMGSZ = int(os.getenv("YOLO26_IMGSZ", "1280"))
BATCH_SIZE = int(os.getenv("YOLO26_BATCH_SIZE", "8"))
REPEAT = int(os.getenv("YOLO26_REPEAT", "1"))
BURN_DURATION_SECONDS = float(os.getenv("YOLO26_BURN_DURATION_SECONDS", "300"))
START_DELAY_SECONDS = float(os.getenv("YOLO26_BURN_START_DELAY_SECONDS", "15"))
WARMUP_ITERS = int(os.getenv("YOLO26_WARMUP_ITERS", "2"))
PROGRESS_INTERVAL_SECONDS = float(os.getenv("YOLO26_PROGRESS_INTERVAL_SECONDS", "5"))
POD_NAME = os.getenv("POD_NAME", os.getenv("HOSTNAME", "unknown"))
NODE_NAME = os.getenv("NODE_NAME", "unknown")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def make_batch_images():
    img = Image.new("RGB", (IMGSZ, IMGSZ), color=(127, 127, 127))
    if BATCH_SIZE <= 1:
        return img
    return [img.copy() for _ in range(BATCH_SIZE)]


def run_predict(model, batch_images):
    last_results = None
    with torch.inference_mode():
        for _ in range(REPEAT):
            last_results = model.predict(
                batch_images,
                device=DEVICE,
                imgsz=IMGSZ,
                batch=BATCH_SIZE,
                verbose=False,
            )
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    return last_results


def count_boxes(results):
    total = 0
    if not results:
        return total
    for item in results:
        boxes = getattr(item, "boxes", None)
        if boxes is not None:
            total += len(boxes)
    return total


def emit(prefix, payload):
    print(f"{prefix}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}", flush=True)


def main():
    model = YOLO(MODEL_NAME)
    batch_images = make_batch_images()

    emit(
        "GPU_BURN_CONFIG_JSON",
        {
            "model": MODEL_NAME,
            "device": DEVICE,
            "imgsz": IMGSZ,
            "batch_size": BATCH_SIZE,
            "repeat": REPEAT,
            "burn_duration_seconds": BURN_DURATION_SECONDS,
            "start_delay_seconds": START_DELAY_SECONDS,
            "warmup_iters": WARMUP_ITERS,
            "progress_interval_seconds": PROGRESS_INTERVAL_SECONDS,
            "pod_name": POD_NAME,
            "node_name": NODE_NAME,
        },
    )

    for idx in range(max(0, WARMUP_ITERS)):
        iter_t0 = time.perf_counter()
        results = run_predict(model, batch_images)
        iter_ms = (time.perf_counter() - iter_t0) * 1000.0
        emit(
            "GPU_BURN_WARMUP_JSON",
            {
                "warmup_iter": idx + 1,
                "iter_ms": round(iter_ms, 3),
                "num_boxes": count_boxes(results),
            },
        )

    if START_DELAY_SECONDS > 0:
        time.sleep(START_DELAY_SECONDS)

    start_wall = time.time()
    start_perf = time.perf_counter()
    next_progress_at = start_perf + PROGRESS_INTERVAL_SECONDS

    iter_count = 0
    total_images = 0
    total_predict_calls = 0
    total_boxes = 0
    iter_ms_values = []

    while (time.perf_counter() - start_perf) < BURN_DURATION_SECONDS:
        iter_t0 = time.perf_counter()
        results = run_predict(model, batch_images)
        iter_ms = (time.perf_counter() - iter_t0) * 1000.0

        iter_count += 1
        total_images += BATCH_SIZE * REPEAT
        total_predict_calls += REPEAT
        total_boxes += count_boxes(results)
        iter_ms_values.append(iter_ms)

        now_perf = time.perf_counter()
        if now_perf >= next_progress_at:
            elapsed = now_perf - start_perf
            recent = iter_ms_values[-20:]
            emit(
                "GPU_BURN_PROGRESS_JSON",
                {
                    "elapsed_s": round(elapsed, 3),
                    "iter_count": iter_count,
                    "total_images": total_images,
                    "total_predict_calls": total_predict_calls,
                    "avg_iter_ms_recent": round(sum(recent) / len(recent), 3),
                    "images_per_second_est": round(total_images / max(elapsed, 1e-6), 3),
                },
            )
            next_progress_at = now_perf + PROGRESS_INTERVAL_SECONDS

    total_elapsed = time.perf_counter() - start_perf
    summary = {
        "success": True,
        "model": MODEL_NAME,
        "device": DEVICE,
        "imgsz": IMGSZ,
        "batch_size": BATCH_SIZE,
        "repeat": REPEAT,
        "pod_name": POD_NAME,
        "node_name": NODE_NAME,
        "start_time_epoch": start_wall,
        "start_time_iso": datetime.fromtimestamp(start_wall, tz=timezone.utc).isoformat(),
        "end_time_iso": now_iso(),
        "duration_seconds": round(total_elapsed, 3),
        "iter_count": iter_count,
        "total_images": total_images,
        "total_predict_calls": total_predict_calls,
        "total_boxes": total_boxes,
        "avg_iter_ms": round(sum(iter_ms_values) / len(iter_ms_values), 3) if iter_ms_values else None,
        "p95_iter_ms": round(sorted(iter_ms_values)[max(0, int(len(iter_ms_values) * 0.95) - 1)], 3)
        if iter_ms_values
        else None,
        "images_per_second": round(total_images / max(total_elapsed, 1e-6), 3),
    }
    emit("GPU_BURN_SUMMARY_JSON", summary)


if __name__ == "__main__":
    main()
