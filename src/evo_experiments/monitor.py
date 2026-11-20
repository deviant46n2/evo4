from datetime import datetime, timezone
import shutil
import subprocess
import threading

def _ram_used_mib():
    try:
        data = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                key, value = line.split(":", 1)
                data[key] = float(value.strip().split()[0])
        return (data["MemTotal"] - data.get("MemAvailable", data["MemFree"])) / 1024
    except (OSError, ValueError, KeyError):
        return None

def _num(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def sample_nvidia_smi():
    sample = {"sampled_at": datetime.now(timezone.utc).isoformat(), "gpu_name": None,
        "gpu_utilization_percent": None, "gpu_memory_used_mib": None,
        "gpu_memory_total_mib": None, "gpu_temperature_c": None,
        "gpu_power_w": None, "ram_used_mib": _ram_used_mib()}
    binary = shutil.which("nvidia-smi")
    if not binary:
        return sample
    query = "name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
    try:
        result = subprocess.run([binary, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=True)
        fields = [v.strip() for v in result.stdout.strip().splitlines()[0].split(",")]
        if len(fields) >= 6:
            sample.update({"gpu_name": fields[0], "gpu_utilization_percent": _num(fields[1]),
                "gpu_memory_used_mib": _num(fields[2]), "gpu_memory_total_mib": _num(fields[3]),
                "gpu_temperature_c": _num(fields[4]), "gpu_power_w": _num(fields[5])})
    except (subprocess.SubprocessError, OSError, IndexError):
        pass
    return sample

class ResourceMonitor:
    def __init__(self, interval, callback):
        self.interval, self.callback = interval, callback
        self.stop_event = threading.Event()
        self.thread = None
    def start(self):
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
        if self.thread and self.thread.is_alive():
            # nvidia-smi itself has a 3-second timeout; wait long enough for it to exit
            # before the caller closes the shared SQLite connection.
            self.thread.join(timeout=max(4.0, self.interval + 3.5))
