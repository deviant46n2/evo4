# Hardware Intelligence v1

This milestone adds an advisory resource-intelligence layer, not a process manager.

- Runtime discovery: `GET /api/v1/hardware/runtimes` recognizes selected inference process names without reading arguments or environment variables. The configured endpoint is reported separately; ownership is not inferred.
- Runtime profiles: `GET/POST /api/v1/hardware/profiles` persists named runtime settings in the experiment database. Saving never launches or changes a runtime.
- Resource estimate: `POST /api/v1/hardware/estimate` reports model-file size and KV cache only when architecture dimensions are supplied. KV cache is context × layers × KV heads × head dimension × (K bytes + V bytes), with a 15% margin. Runtime buffers, CUDA allocations, fragmentation, offload and overhead are excluded. Fit remains unknown rather than guessed.
- Workload admission: `POST /api/v1/hardware/admission` returns allow/defer/unknown advice using live telemetry, a 1 GiB VRAM reserve and 2 GiB RAM reserve. Background work requires an explicit RAM estimate and available-RAM telemetry; GPU-heavy work (the default unless explicitly declared CPU-only) also requires a VRAM estimate and GPU telemetry. Missing requirements return unknown rather than allow. Interactive work has higher advisory priority; nothing is preempted. Unknown GPU capacity or demand fails closed for GPU-heavy work.

## Safety

Runtime discovery and resource estimates are read-only. Runtime profiles and scheduler queue/lifecycle records are persisted in SQLite. Evo does not signal PIDs, kill processes, start/stop services, alter GPU clocks/power, or edit runtime launch settings. The standalone admission endpoint is advisory and does not reserve capacity; the scheduler serializes its own unstarted reservations, but estimates can still differ from actual consumption. A workload marked CPU-only is trusted as declared; Evo does not inspect its code to verify that it avoids GPU use.

## Limitations

Discovery and telemetry are Linux/NVIDIA-oriented. Architecture values must be accurate; GGUF metadata parsing is not implemented. Model-file size is not equivalent to VRAM residency. Profiles are records, not automatically applied configurations. Experiment aggregates remain the source of measured throughput, TTFT and resource comparisons.


## Hardware Intelligence v2: persistent workload scheduler

The scheduler adds a durable queue and explicit resource reservations:

- Jobs are stored in `workload_jobs` in the shared Evo Lab SQLite database.
- Queue order is priority descending, then creation time ascending.
- Dispatch evaluates queued jobs against fresh hardware telemetry and currently outstanding unstarted reservations. It reserves only jobs whose RAM/VRAM estimates and telemetry satisfy the existing protected reserves.
- Missing estimates or telemetry leave a job queued with an explicit `unknown` decision. Insufficient headroom leaves it queued with `defer`.
- Reservations expire after five minutes if the user does not confirm an external start. Expired reservations return to the queue.
- A user confirms that a reserved workload has been started externally. Running jobs remain durable across Evo restarts and must be explicitly marked completed or failed when the external process ends.
- Queued and reserved jobs can be cancelled. A running job cannot be cancelled through Evo because that would imply stopping an external process; the scheduler never signals or terminates PIDs.
- CPU-only declarations are trusted input. Evo does not inspect workload code to verify that it avoids GPU use.

API routes:
- `GET /api/v1/hardware/scheduler`
- `POST /api/v1/hardware/scheduler/jobs`
- `POST /api/v1/hardware/scheduler/dispatch?limit=5`
- `POST /api/v1/hardware/scheduler/jobs/{id}/start`
- `POST /api/v1/hardware/scheduler/jobs/{id}/finish`
- `POST /api/v1/hardware/scheduler/jobs/{id}/cancel`

This is a reservation ledger, not an execution engine or hard real-time scheduler. Reservations are advisory estimates; actual consumption can differ. Running jobs are not subtracted from telemetry again because their resource use should already appear in live system measurements. The scheduler does not launch commands, inspect process arguments, manage model servers, interrupt workloads, or guarantee resource isolation. It also does not automatically reconcile an externally terminated process after a crash; the user must update the persisted job state.
