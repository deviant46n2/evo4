from dataclasses import dataclass
from pathlib import Path
import os
import tomllib

from .provider_approvals import ProviderApprovalError, parse_provider_approvals
from .provider_endpoint import ProviderEndpointError, normalize_provider_origin
from .secret_references import SecretResolutionError, resolve_secret_references
from .dispatch_admission import AdmissionError, ProviderBudget, ResourceDemand

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
    workspace_root: Path = Path(".")
    allowed_commands: tuple = ()
    max_history_chars: int = 40000
    context_window_tokens: int = 49152
    provider_name: str = "default"
    allowed_provider_origins: tuple[str, ...] = ()
    allowed_secret_env_vars: tuple[str, ...] = ()
    provider_approvals: tuple = ()
    provider_budgets: tuple = ()
    dispatch_enabled: bool = False
    local_resource_profiles: tuple = ()

def load_config(path: str | Path = "config.toml", provider_name: str | None = None) -> EvoConfig:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Config file not found: {source}. Copy config.example.toml to config.toml.")
    with source.open("rb") as handle:
        raw = tomllib.load(handle)
    server = raw.get("server", {})
    experiment = raw.get("experiment", {})
    system = raw.get("system", {})
    assistant = raw.get("assistant", {})
    workspace = raw.get("workspace", {})
    profiles = raw.get("providers", {})
    security = raw.get("security", {})
    secrets = raw.get("secrets", {})
    dispatch = raw.get("dispatch", {})
    if not isinstance(dispatch, dict) or set(dispatch) - {"enabled", "provider_budgets", "local_resource_profiles"}:
        raise ValueError("dispatch must contain only enabled, provider_budgets, and local_resource_profiles")
    if not isinstance(security, dict) or set(security) - {"allowed_provider_origins"}:
        raise ValueError("security must contain only allowed_provider_origins")
    if not isinstance(secrets, dict) or set(secrets) - {"allowed_env_vars"}:
        raise ValueError("secrets must contain only allowed_env_vars")
    raw_origins = security.get("allowed_provider_origins", [])
    if not isinstance(raw_origins, list) or len(raw_origins) > 128:
        raise ValueError("security.allowed_provider_origins must be a list of at most 128 exact origins")
    try:
        allowed_origins = tuple(normalize_provider_origin(origin) for origin in raw_origins)
    except (ProviderEndpointError, TypeError) as exc:
        raise ValueError("security.allowed_provider_origins contains an invalid exact origin") from exc
    if len(allowed_origins) != len(set(allowed_origins)):
        raise ValueError("security.allowed_provider_origins contains duplicate origins")
    allowed_env_vars = secrets.get("allowed_env_vars", [])
    if not isinstance(allowed_env_vars, list) or len(allowed_env_vars) > 128:
        raise ValueError("secrets.allowed_env_vars must be a list of at most 128 names")
    try:
        resolve_secret_references({}, allowed_env_vars)
    except SecretResolutionError as exc:
        raise ValueError("secrets.allowed_env_vars must contain valid environment-variable names") from exc
    if len(allowed_env_vars) != len(set(allowed_env_vars)):
        raise ValueError("secrets.allowed_env_vars contains duplicate names")
    provider_approvals_raw = raw.get("provider_approvals", [])
    try:
        provider_approvals = parse_provider_approvals(provider_approvals_raw)
    except ProviderApprovalError as exc:
        raise ValueError(str(exc)) from exc
    dispatch_enabled = dispatch.get("enabled", False)
    if not isinstance(dispatch_enabled, bool):
        raise ValueError("dispatch.enabled must be a boolean")
    raw_budgets = dispatch.get("provider_budgets", [])
    if not isinstance(raw_budgets, list) or len(raw_budgets) > 128:
        raise ValueError("dispatch.provider_budgets must be a bounded list of tables")
    provider_budgets = []
    budget_ids = set()
    for index, item in enumerate(raw_budgets):
        if not isinstance(item, dict) or set(item) != {
            "integration_id", "maximum_requests_per_utc_day",
            "maximum_output_tokens_per_invocation",
            "maximum_reserved_output_tokens_per_utc_day",
        }:
            raise ValueError(f"dispatch.provider_budgets[{index}] has missing or unknown fields")
        try:
            budget = ProviderBudget(**item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"dispatch.provider_budgets[{index}] is invalid") from exc
        if budget.integration_id in budget_ids:
            raise ValueError("dispatch.provider_budgets contains duplicate integration IDs")
        budget_ids.add(budget.integration_id)
        provider_budgets.append(budget)

    raw_profiles = dispatch.get("local_resource_profiles", [])
    if not isinstance(raw_profiles, list) or len(raw_profiles) > 128:
        raise ValueError("dispatch.local_resource_profiles must be a bounded list of tables")
    local_resource_profiles = []
    profile_ids = set()
    for index, item in enumerate(raw_profiles):
        required = {"integration_id", "compute_mode", "cpu_cores", "ram_mib", "memory_mode"}
        allowed = required | {"gpu_vram_mib", "maximum_gpu_temperature_c"}
        if not isinstance(item, dict) or required - set(item) or set(item) - allowed:
            raise ValueError(f"dispatch.local_resource_profiles[{index}] has missing or unknown fields")
        integration_id = item.get("integration_id")
        if not isinstance(integration_id, str) or not integration_id.strip() or len(integration_id) > 128:
            raise ValueError(f"dispatch.local_resource_profiles[{index}] integration_id is invalid")
        if integration_id in profile_ids:
            raise ValueError("dispatch.local_resource_profiles contains duplicate integration IDs")
        profile = {key: value for key, value in item.items() if key != "integration_id"}
        try:
            ResourceDemand(
                locality="local_endpoint",
                cpu_cores=profile["cpu_cores"],
                ram_mib=profile["ram_mib"],
                gpu_vram_mib=profile.get("gpu_vram_mib"),
                compute_mode=profile["compute_mode"],
                memory_mode=profile["memory_mode"],
                maximum_gpu_temperature_c=profile.get("maximum_gpu_temperature_c", 85.0),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"dispatch.local_resource_profiles[{index}] is invalid") from exc
        profile_ids.add(integration_id)
        local_resource_profiles.append((integration_id, profile))

    selected_provider = provider_name or server.get("profile")
    profile = {}
    if selected_provider:
        if not isinstance(profiles, dict) or selected_provider not in profiles:
            available=", ".join(sorted(profiles)) if isinstance(profiles,dict) else ""
            raise ValueError(f"Unknown provider profile {selected_provider!r}. Available profiles: {available or 'none'}")
        profile=profiles[selected_provider]
        if not isinstance(profile,dict):
            raise ValueError(f"Provider profile {selected_provider!r} must be a TOML table")
    api_key_env=str(profile.get("api_key_env","")).strip()
    if api_key_env and api_key_env not in os.environ:
        raise ValueError(f"Provider profile {selected_provider!r} requires environment variable {api_key_env}")
    profile_api_key=os.environ.get(api_key_env) if api_key_env else profile.get("api_key")
    raw_commands = workspace.get("allowed_commands", [])
    if not isinstance(raw_commands, list):
        raise ValueError("workspace.allowed_commands must be a list of argv lists")
    allowed_commands = []
    for command in raw_commands:
        if not isinstance(command, (list, tuple)) or not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("workspace.allowed_commands entries must be non-empty lists of strings")
        allowed_commands.append(tuple(command))
    allowed_commands = tuple(allowed_commands)
    return EvoConfig(
        base_url=str(profile.get("base_url",server.get("base_url", "http://127.0.0.1:18997"))).rstrip("/"),
        api_key=str(profile_api_key if profile_api_key is not None else server.get("api_key", "no-key")),
        model=str(profile.get("model",server.get("model", "local-model"))),
        timeout_seconds=max(1, int(profile.get("timeout_seconds",server.get("timeout_seconds", 600)))),
        database=Path(experiment.get("database", "results/experiments.sqlite3")),
        max_tokens=max(1, int(assistant.get("max_tokens", experiment.get("max_tokens", 2048)))),
        temperature=max(0.0, float(assistant.get("temperature", experiment.get("temperature", 0.2)))),
        system_prompt=str(system.get("prompt", "You are Evo, a careful local-first AI assistant. Be honest about uncertainty and distinguish evidence from inference.")),
        memory_limit=max(1, int(assistant.get("memory_limit", 8))),
        history_messages=max(2, int(assistant.get("history_messages", 16))),
        workspace_root=Path(workspace.get("root", ".")),
        allowed_commands=allowed_commands,
        max_history_chars=max(2000,int(assistant.get("max_history_chars",40000))),
        context_window_tokens=max(4096,int(assistant.get("context_window_tokens",49152))),
        provider_name=str(selected_provider or "default"),
        allowed_provider_origins=allowed_origins,
        allowed_secret_env_vars=tuple(allowed_env_vars),
        provider_approvals=provider_approvals,
        provider_budgets=tuple(provider_budgets),
        dispatch_enabled=dispatch_enabled,
        local_resource_profiles=tuple(local_resource_profiles),
    )
