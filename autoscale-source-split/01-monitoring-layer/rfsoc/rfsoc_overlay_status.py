#!/usr/bin/env python3
"""Emit the RFSoC overlay status consumed by vm_agg_rfsoc.py.

Install as /home/xilinx/rfsoc_overlay_status.py on the RFSoC.  It is executed
by the existing root-owned rfsoc-overlay-status*.service units every 30 seconds.
"""
import glob
import json
import subprocess
import time


result = {
    "ts": int(time.time()), "hostname": "pynq", "board": "RFSoC4x2",
    "xrt_device_ready": 0, "active_bitfile": None, "overlay_loaded": 0,
    "ip_count": 0, "has_rfdc": 0, "has_dma": 0, "has_sysmon": 0,
    "dma_mm2s_state": "unavailable", "dma_s2mm_state": "unavailable",
    "dma_channels_status": "unavailable", "temperature_c": None,
    "temperature_source": None, "temperature_policy": "max_valid_ams_temp",
    "ams_temperatures": {}, "vccint_v": None, "vccaux_v": None,
    "status": "unknown", "error": None,
}


def set_error(prefix, exc):
    message = f"{prefix}: {exc}"
    result["error"] = f"{result['error']}; {message}" if result["error"] else message


def maybe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def read_xilinx_ams_temps():
    temps, best_temp, best_source = {}, None, None
    for dev in glob.glob("/sys/bus/iio/devices/iio:device*"):
        try:
            with open(f"{dev}/name") as handle:
                if handle.read().strip() != "xilinx-ams":
                    continue
        except Exception:
            continue
        for path in glob.glob(f"{dev}/in_temp*_input"):
            try:
                with open(path) as handle:
                    temp_c = int(handle.read().strip()) / 1000.0
            except Exception:
                continue
            if not 0 <= temp_c <= 125:
                continue
            key = path.split("/")[-1].replace("_input", "")
            temps[key] = {"celsius": temp_c, "path": path}
            if best_temp is None or temp_c > best_temp:
                best_temp, best_source = temp_c, path
    return best_temp, best_source, temps


def update_power_telemetry():
    try:
        from pynq.pmbus import get_rails
        rails = get_rails()
        for name in ("VCCp0V85", "vccint", "VCCINT"):
            rail = rails.get(name)
            if rail and rail.voltage is not None:
                result["vccint_v"] = maybe_float(rail.voltage.value)
                break
        for name in ("VADC_AVCCAUX", "VCCAUX", "vccaux"):
            rail = rails.get(name)
            if rail and rail.voltage is not None:
                result["vccaux_v"] = maybe_float(rail.voltage.value)
                break
    except Exception as exc:
        set_error("pmbus_error", exc)


DMA_ERROR_MASK = 0x4770  # IntErr, SlvErr, DecErr, SG errors, Err_Irq


def dma_channel_state(dma, control_offset, status_offset):
    """Return a runtime health state; Idle is valid when no transfer is queued."""
    control = int(dma.read(control_offset))
    status = int(dma.read(status_offset))
    running = bool(control & 0x1)  # AXI DMA DMACR.RS
    halted = bool(status & 0x1)    # AXI DMA DMASR.Halted
    has_error = bool(status & DMA_ERROR_MASK)
    if has_error:
        state = "error"
    elif running and not halted:
        state = "ready"
    else:
        state = "degraded"
    return state, control, status, halted, has_error


def update_dma_telemetry(overlay):
    try:
        dma = overlay.CMAC.axi_dma
        mm2s, mm2s_cr, mm2s_sr, mm2s_halted, mm2s_error = dma_channel_state(dma, 0x00, 0x04)
        s2mm, s2mm_cr, s2mm_sr, s2mm_halted, s2mm_error = dma_channel_state(dma, 0x30, 0x34)
        result.update({
            "dma_mm2s_state": mm2s, "dma_s2mm_state": s2mm,
            "dma_mm2s_dmacr": f"0x{mm2s_cr:08x}", "dma_mm2s_dmasr": f"0x{mm2s_sr:08x}",
            "dma_s2mm_dmacr": f"0x{s2mm_cr:08x}", "dma_s2mm_dmasr": f"0x{s2mm_sr:08x}",
            "dma_mm2s_halted": int(mm2s_halted), "dma_s2mm_halted": int(s2mm_halted),
            "dma_mm2s_error": int(mm2s_error), "dma_s2mm_error": int(s2mm_error),
        })
        result["dma_channels_status"] = "ready" if mm2s == s2mm == "ready" else (
            "error" if "error" in (mm2s, s2mm) else "degraded"
        )
    except Exception as exc:
        set_error("dma_status_error", exc)


try:
    xbutil = subprocess.run(["xbutil", "examine"], text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=10)
    if "Device Ready" in xbutil.stdout and "Yes" in xbutil.stdout and "RFSoC4x2" in xbutil.stdout:
        result["xrt_device_ready"] = 1
except Exception as exc:
    set_error("xbutil_error", exc)

try:
    from pynq import Device, Overlay
    bitfile = "/usr/local/share/pynq-venv/lib/python3.10/site-packages/pynq/overlays/base/base.bit"
    overlay = Overlay(bitfile)
    result["active_bitfile"] = getattr(Device.active_device, "bitfile_name", None)
    result["overlay_loaded"] = 1
    result["ip_count"] = len(overlay.ip_dict)
    keys = list(overlay.ip_dict)
    result["has_rfdc"] = int(any("rfdc" in key.lower() for key in keys))
    result["has_dma"] = int(any("dma" in key.lower() for key in keys))
    result["has_sysmon"] = int(any("system_management" in key.lower() or "sysmon" in key.lower() for key in keys))
    if result["has_dma"]:
        update_dma_telemetry(overlay)
    update_power_telemetry()
    result["status"] = "ok"
except Exception as exc:
    result["status"] = "error"
    set_error("pynq_error", exc)

temp_c, source, temps = read_xilinx_ams_temps()
result.update({"temperature_c": temp_c, "temperature_source": source, "ams_temperatures": temps})
print(json.dumps(result, indent=2))
