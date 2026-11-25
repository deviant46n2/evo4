"""Low-overhead Linux/NVIDIA telemetry shared by Evo Lab and the desktop API."""
from datetime import datetime, timezone
import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time


_cpu_lock = threading.Lock()
_previous_cpu = None


def _ram():
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            values[key] = float(value.strip().split()[0]) * 1024
        total = values["MemTotal"]
        available = values.get("MemAvailable", values.get("MemFree", 0))
        used = max(0.0, total - available)
        return {
            "ram_total_bytes": total,
            "ram_available_bytes": available,
            "ram_used_bytes": used,
            "ram_used_mib": used / (1024 * 1024),
            "ram_used_percent": (used / total * 100) if total else None,
        }
    except (OSError, ValueError, KeyError):
        return {"ram_total_bytes": None, "ram_available_bytes": None,
                "ram_used_bytes": None, "ram_used_mib": None, "ram_used_percent": None}


def _cpu():
    global _previous_cpu
    result = {"cpu_utilization_percent": None, "cpu_logical_cores": os.cpu_count(),
              "load_average_1m": None, "load_average_5m": None, "load_average_15m": None}
    try:
        fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
        counters = [int(value) for value in fields]
        idle = counters[3] + (counters[4] if len(counters) > 4 else 0)
        total = sum(counters)
        with _cpu_lock:
            previous = _previous_cpu
            _previous_cpu = (total, idle)
        if previous:
            delta_total, delta_idle = total - previous[0], idle - previous[1]
            if delta_total > 0:
                result["cpu_utilization_percent"] = round(
                    max(0.0, min(100.0, (delta_total - delta_idle) / delta_total * 100)), 1)
    except (OSError, ValueError, IndexError):
        pass
    try:
        load = os.getloadavg()
        result.update({"load_average_1m": load[0], "load_average_5m": load[1],
                       "load_average_15m": load[2]})
    except (OSError, AttributeError):
        pass
    return result


def _gpu_processes(binary):
    try:
        result = subprocess.run(
            [binary, "--query-compute-apps=pid,process_name,used_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=True)
        rows = []
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row) < 3:
                continue
            try:
                pid = int(row[0].strip())
                used = float(row[2].strip())
            except ValueError:
                continue
            # Do not expose raw argv: model-server command lines can contain
            # credentials or other sensitive launch parameters.
            rows.append({"pid": pid, "process_name": row[1].strip(),
                         "memory_used_mib": used})
        return rows
    except (subprocess.SubprocessError, OSError):
        return []


def sample_nvidia_smi():
    collection_started = time.monotonic()
    sample = {
        "gpu_name": None, "gpu_utilization_percent": None,
        "gpu_memory_used_mib": None, "gpu_memory_total_mib": None,
        "gpu_memory_used_percent": None, "gpu_temperature_c": None,
        "gpu_power_w": None, "gpu_processes": [], "gpu_available": False,
    }
    sample.update(_ram())
    sample.update(_cpu())
    binary = shutil.which("nvidia-smi")
    if binary:
        query = "name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
        try:
            result = subprocess.run([binary, f"--query-gpu={query}",
                "--format=csv,noheader,nounits"], capture_output=True, text=True,
                timeout=3, check=True)
            rows = list(csv.reader(io.StringIO(result.stdout)))
            if rows and len(rows[0]) >= 6:
                fields = [value.strip() for value in rows[0]]
                def number(value):
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        return None
                used, total = number(fields[2]), number(fields[3])
                sample.update({
                    "gpu_name": fields[0],
                    "gpu_utilization_percent": number(fields[1]),
                    "gpu_memory_used_mib": used,
                    "gpu_memory_total_mib": total,
                    "gpu_memory_used_percent": (used / total * 100) if used is not None and total else None,
                    "gpu_temperature_c": number(fields[4]),
                    "gpu_power_w": number(fields[5]),
                    "gpu_available": True,
                })
                sample["gpu_processes"] = _gpu_processes(binary)
        except (subprocess.SubprocessError, OSError, IndexError):
            pass
    # Timestamp only after every bounded probe has completed. Admission freshness
    # must describe when this complete snapshot became available, not when it began.
    sample["sampled_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    sample["collection_duration_seconds"] = round(max(0.0, time.monotonic() - collection_started), 6)
    return sample


class ResourceMonitor:
    def __init__(self, interval, callback):
        self.interval, self.callback = interval, callback
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.callback(sample_nvidia_smi())
            except Exception:
                pass
            self.stop_event.wait(self.interval)

    def stop(self):
        self.stop_event.set()
        thread = self.thread
        if thread is None or not thread.is_alive():
            self.thread = None
            return
        if thread is threading.current_thread():
            raise RuntimeError("ResourceMonitor.stop() cannot be called from its worker thread")
        interrupted = False
        unexpected = None
        while thread.is_alive():
            try:
                thread.join()
            except KeyboardInterrupt:
                interrupted = True
            except BaseException as exc:  # Defensive: keep waiting even if join is interrupted unexpectedly.
                unexpected = exc
        self.thread = None
        if unexpected is not None:
            raise unexpected
        if interrupted:
            raise KeyboardInterrupt
