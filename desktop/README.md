# Evo desktop preview

This directory contains the first functional React/Vite client for Evo 4.

## Run

From the repository root, install the optional Python API dependencies:

```bash
python -m pip install -e '.[desktop]'
```

Start the backend in terminal one:

```bash
evo serve
```

Install and start the frontend in terminal two:

```bash
cd desktop
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

The UI currently supports conversation creation, persistent conversation history, streamed responses, and configured provider/model display. Other navigation entries are placeholders and are intentionally disabled. The backend binds to loopback only. Provider API keys stay server-side.

This is a development preview, not a packaged desktop app. Stop-generation, provider switching, markdown rendering, and the remaining workspace screens are not implemented yet.
