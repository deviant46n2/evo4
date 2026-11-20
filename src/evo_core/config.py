from dataclasses import dataclass
from pathlib import Path
import tomllib

@dataclass(frozen=True)
class EvoConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int
    database: Path
    max_tokens: int
    temperature: float
    system_prompt: str
    memory_limit: int
    history_messages: int

def load_config(path: str | Path = "config.toml") -> EvoConfig:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Config file not found: {source}. Copy config.example.toml to config.toml.")
    with source.open("rb") as handle:
        raw = tomllib.load(handle)
    server = raw.get("server", {})
    experiment = raw.get("experiment", {})
    system = raw.get("system", {})
    assistant = raw.get("assistant", {})
    return EvoConfig(
        base_url=str(server.get("base_url", "http://127.0.0.1:18997")).rstrip("/"),
        api_key=str(server.get("api_key", "no-key")),
        model=str(server.get("model", "local-model")),
        timeout_seconds=max(1, int(server.get("timeout_seconds", 600))),
        database=Path(experiment.get("database", "results/experiments.sqlite3")),
        max_tokens=max(1, int(assistant.get("max_tokens", experiment.get("max_tokens", 2048)))),
        temperature=max(0.0, float(assistant.get("temperature", experiment.get("temperature", 0.2)))),
        system_prompt=str(system.get("prompt", "You are Evo, a careful local-first AI assistant. Be honest about uncertainty and distinguish evidence from inference.")),
        memory_limit=max(1, int(assistant.get("memory_limit", 8))),
        history_messages=max(2, int(assistant.get("history_messages", 16))),
    )
