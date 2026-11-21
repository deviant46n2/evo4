# Hardware Intelligence v1

This milestone adds an advisory resource-intelligence layer, not a process manager.

- Runtime discovery: `GET /api/v1/hardware/runtimes` recognizes selected inference process names without reading arguments or environment variables. The configured endpoint is reported separately; ownership is not inferred.
- Runtime profiles: `GET/POST /api/v1/hardware/profiles` persists named runtime settings in the experiment database. Saving never launches or changes a runtime.
- Resource estimate: `POST /api/v1/hardware/estimate` reports model-file size and KV cache only when architecture dimensions are supplied. KV cache is context × layers × KV heads × head dimension × (K bytes + V bytes), with a 15% margin. Runtime buffers, CUDA allocations, fragmentation, offload and overhead are excluded. Fit remains unknown rather than guessed.
- Workload admission: `POST /api/v1/hardware/admission` returns allow/defer/unknown advice using live telemetry, a 1 GiB VRAM reserve and 2 GiB RAM reserve. Interactive work has higher advisory priority; nothing is preempted. Unknown GPU capacity or demand fails closed for GPU-heavy work.

## Safety

All operations are read-only or persist user-authored profile data. Evo does not signal PIDs, kill processes, start/stop services, alter GPU clocks/power, or edit runtime launch settings. Admission decisions do not reserve resources; concurrent callers can invalidate an estimate.

## Limitations

Discovery and telemetry are Linux/NVIDIA-oriented. Architecture values must be accurate; GGUF metadata parsing is not implemented. Model-file size is not equivalent to VRAM residency. Profiles are records, not automatically applied configurations. Experiment aggregates remain the source of measured throughput, TTFT and resource comparisons.
