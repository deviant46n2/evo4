"""Safe, advisory-only resource intelligence for Evo."""
from pathlib import Path
import time

RUNTIMES = {"llama-server":"llama.cpp", "ollama":"ollama", "vllm":"vLLM",
            "lmstudio":"LM Studio", "lm-studio":"LM Studio", "aphrodite":"Aphrodite"}

def discover_runtimes(gpu_processes=None, configured=None, proc_root="/proc"):
    """Identify process names only. Never read argv, environ or command-line secrets."""
    found=[]
    try: entries=list(Path(proc_root).iterdir())
    except OSError: entries=[]
    gpu={int(p["pid"]):p for p in (gpu_processes or []) if str(p.get("pid","")).isdigit()}
    for entry in entries:
        if not entry.name.isdigit(): continue
        try: name=(entry/"comm").read_text(encoding="utf-8").strip()
        except (OSError,UnicodeError): continue
        runtime=next((v for k,v in RUNTIMES.items() if k in name.casefold()),None)
        if not runtime: continue
        pid=int(entry.name); gp=gpu.get(pid)
        found.append({"pid":pid,"name":name[:100],"runtime":runtime,
                      "gpu_process":bool(gp),
                      "gpu_memory_used_mib":gp.get("memory_used_mib") if gp else None,
                      "identity_verified":True})
    return {"discovered_at":time.time(),"processes":found,"configured_endpoint":configured or {},
            "limitations":["Process-name recognition is heuristic.",
            "Configured endpoint ownership is not inferred from process identity.",
            "Arguments and environment variables are never read or returned."]}

def kv_cache_estimate_mib(context_size,layers,kv_heads,head_dim,key_bytes=2,value_bytes=2,safety_factor=1.15):
    values=(context_size,layers,kv_heads,head_dim,key_bytes,value_bytes)
    if any(not isinstance(v,int) or isinstance(v,bool) or v<=0 for v in values):
        raise ValueError("KV estimate inputs must be positive integers")
    if not isinstance(safety_factor,(int,float)) or not 1<=safety_factor<=2:
        raise ValueError("safety_factor must be between 1 and 2")
    return round(context_size*layers*kv_heads*head_dim*(key_bytes+value_bytes)/1048576*safety_factor,1)

def estimate_runtime(profile,sample):
    dims=(profile.get("context_size"),profile.get("layers"),profile.get("kv_heads"),
          profile.get("head_dim"),profile.get("key_bytes",2),profile.get("value_bytes",2))
    kv=kv_cache_estimate_mib(*dims) if all(isinstance(v,int) and not isinstance(v,bool) and v>0 for v in dims) else None
    size=profile.get("model_file_bytes")
    weights=round(size/1048576,1) if isinstance(size,int) and size>0 else None
    vram=None
    if sample.get("gpu_memory_total_mib") is not None and sample.get("gpu_memory_used_mib") is not None:
        vram=max(0,sample["gpu_memory_total_mib"]-sample["gpu_memory_used_mib"])
    ram=sample.get("ram_available_bytes")
    return {"model_weights_mib":weights,"kv_cache_mib_estimate":kv,
      "kv_cache_method":"architecture-derived K+V estimate with 15% margin" if kv is not None else "unknown: supply architecture dimensions and KV element sizes",
      "vram_free_mib":vram,"ram_free_mib":round(ram/1048576,1) if isinstance(ram,(int,float)) else None,
      "fit_assessment":"unknown",
      "warnings":["Weights are not equivalent to GPU residency; runtime buffers, CUDA allocations, fragmentation, offload distribution and overhead are excluded."]}

def assess_workload(sample,workload,reserve_vram_mib=1024,reserve_ram_mib=2048):
    kind=workload.get("kind","background")
    gpu_value=workload.get("gpu_heavy")
    gpu=bool(kind in {"inference","benchmark","training"} if gpu_value is None else gpu_value)
    demand=workload.get("estimated_vram_mib"); ram_demand=workload.get("estimated_ram_mib")
    free_vram=None
    if sample.get("gpu_memory_total_mib") is not None and sample.get("gpu_memory_used_mib") is not None:
        free_vram=max(0,sample["gpu_memory_total_mib"]-sample["gpu_memory_used_mib"])
    free_ram=sample.get("ram_available_bytes")
    free_ram=free_ram/1048576 if isinstance(free_ram,(int,float)) else None
    reasons=[]; decision="allow"
    if gpu and (free_vram is None or not isinstance(demand,(int,float))):
        decision="unknown"; reasons.append("GPU headroom or workload VRAM estimate is unknown.")
    elif gpu and free_vram-reserve_vram_mib<demand:
        decision="defer"; reasons.append("Estimated VRAM demand would consume the protected reserve.")
    elif ram_demand is not None and (free_ram is None or free_ram-reserve_ram_mib<ram_demand):
        decision="unknown" if free_ram is None else "defer"
        reasons.append("Host RAM headroom is unknown or below the protected reserve.")
    elif sample.get("gpu_temperature_c") is not None and sample["gpu_temperature_c"]>=85:
        decision="defer"; reasons.append("GPU temperature is at or above 85°C.")
    elif sample.get("ram_used_percent") is not None and sample["ram_used_percent"]>=90:
        decision="defer"; reasons.append("System RAM usage is at or above 90%.")
    elif kind in {"chat","interactive"}: reasons.append("Interactive work receives priority; no process is preempted.")
    else: reasons.append("Telemetry clears the configured reserve; this is advisory, not a guarantee.")
    return {"decision":decision,"priority":100 if kind in {"chat","interactive"} else 10,
      "preemption":False,"process_actions":False,"reasons":reasons,
      "observed_vram_free_mib":free_vram,"observed_ram_free_mib":free_ram}

PROFILE_SCHEMA="""CREATE TABLE IF NOT EXISTS runtime_profiles (
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, model TEXT NOT NULL DEFAULT '',
 model_file TEXT NOT NULL DEFAULT '', runtime TEXT NOT NULL DEFAULT '', context_size INTEGER,
 gpu_layers TEXT NOT NULL DEFAULT '', kv_cache_k TEXT NOT NULL DEFAULT '', kv_cache_v TEXT NOT NULL DEFAULT '',
 batch_size INTEGER, ubatch_size INTEGER, notes TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""

def initialize_profiles(connection):
    connection.execute(PROFILE_SCHEMA); connection.commit()

def save_profile(connection,profile):
    import uuid
    name=str(profile.get("name","")).strip()
    if not name or len(name)>100: raise ValueError("Profile name must contain 1-100 characters")
    context=profile.get("context_size")
    if context is not None and (not isinstance(context,int) or isinstance(context,bool) or not 1<=context<=10000000):
        raise ValueError("context_size must be a positive integer")
    values={"id":str(profile.get("id") or uuid.uuid4().hex),"name":name,
      "model":str(profile.get("model",""))[:200],"model_file":str(profile.get("model_file",""))[:1000],
      "runtime":str(profile.get("runtime",""))[:100],"context_size":context,
      "gpu_layers":str(profile.get("gpu_layers",""))[:40],"kv_cache_k":str(profile.get("kv_cache_k",""))[:40],
      "kv_cache_v":str(profile.get("kv_cache_v",""))[:40],"batch_size":profile.get("batch_size"),
      "ubatch_size":profile.get("ubatch_size"),"notes":str(profile.get("notes",""))[:4000]}
    for key in ("batch_size","ubatch_size"):
        v=values[key]
        if v is not None and (not isinstance(v,int) or isinstance(v,bool) or not 1<=v<=1000000):
            raise ValueError(key+" must be a positive integer")
    connection.execute("""INSERT INTO runtime_profiles
      (id,name,model,model_file,runtime,context_size,gpu_layers,kv_cache_k,kv_cache_v,batch_size,ubatch_size,notes)
      VALUES (:id,:name,:model,:model_file,:runtime,:context_size,:gpu_layers,:kv_cache_k,:kv_cache_v,:batch_size,:ubatch_size,:notes)
      ON CONFLICT(id) DO UPDATE SET name=excluded.name,model=excluded.model,model_file=excluded.model_file,
      runtime=excluded.runtime,context_size=excluded.context_size,gpu_layers=excluded.gpu_layers,
      kv_cache_k=excluded.kv_cache_k,kv_cache_v=excluded.kv_cache_v,batch_size=excluded.batch_size,
      ubatch_size=excluded.ubatch_size,notes=excluded.notes,updated_at=CURRENT_TIMESTAMP""",values)
    connection.commit(); return values

def list_profiles(connection):
    return [dict(row) for row in connection.execute("SELECT * FROM runtime_profiles ORDER BY updated_at DESC,name").fetchall()]
