from dataclasses import dataclass
from pathlib import Path
import tomllib

@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int
    database: Path
    sample_interval_seconds: float
    max_tokens: int
    temperature: float
    repetitions: int
    system_prompt: str
    run_metadata: dict
    seed: int | None = None

def load_config(path: str | Path) -> Config:
    with Path(path).open("rb") as handle:
        raw = tomllib.load(handle)
    server, exp, system = raw.get("server", {}), raw.get("experiment", {}), raw.get("system", {})
    run = raw.get("run", {})
    seed = exp.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValueError("experiment.seed must be an integer or omitted")
    return Config(
        base_url=str(server.get("base_url", "http://127.0.0.1:18997")).rstrip("/"),
        api_key=str(server.get("api_key", "no-key")),
        model=str(server.get("model", "local-model")),
        timeout_seconds=max(1, int(server.get("timeout_seconds", 600))),
        database=Path(exp.get("database", "results/experiments.sqlite3")),
        sample_interval_seconds=max(0.2, float(exp.get("sample_interval_seconds", 1.0))),
        max_tokens=max(1, int(exp.get("max_tokens", 256))),
        temperature=max(0.0, float(exp.get("temperature", 0.0))),
        repetitions=max(1, int(exp.get("repetitions", 1))),
        system_prompt=str(system.get("prompt", "You are a helpful assistant.")),
        run_metadata=dict(run),
        seed=seed,
    )
