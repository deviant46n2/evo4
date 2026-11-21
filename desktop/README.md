# Evo 4 desktop preview

This directory contains the React/Vite browser client for Evo 4. It is a local development preview, not a packaged native desktop application.

For complete requirements, setup, workspace behavior, limitations, and troubleshooting, see [the desktop user guide](../docs/DESKTOP-USER-GUIDE.md).

## Quick start

From the repository root, create/activate the virtual environment and install the optional API dependencies:

```bash
source .venv/bin/activate
python -m pip install -e '.[desktop]'
```

In terminal one, from the repository root:

```bash
evo serve
```

In terminal two, also from the repository root:

```bash
cd desktop
npm install
npm run dev
```

Open the local Vite URL printed by the command (normally `http://127.0.0.1:5173`). The API binds to `127.0.0.1:8765`.

The current UI workspaces are Chat, Agents, Memory, Hardware, and Experiments. Provider credentials remain in the Python process and are not sent to the browser. The CLI remains supported.

## Current boundaries

- No stop-generation control; closing a browser stream does not guarantee provider cancellation.
- Agent file writes and allowlisted commands require explicit approval.
- Agent pause/resume/redirect and unattended background execution are not implemented.
- Hardware telemetry and resource advice are observe-only; Evo does not control other processes, GPU clocks, power limits, or services.
- Experiments are currently viewed in the desktop; use `evo-exp` commands to initialize and run experiments.
- Provider switching is configured server-side, not selected interactively in the current UI.
