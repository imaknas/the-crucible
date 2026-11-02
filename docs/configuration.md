# Configuration

Settings are environment variables, read from `backend/.env` (copy [`.env.example`](../.env.example)) or the environment. Only a provider key is needed.

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | At least one* | OpenAI API key |
| `ANTHROPIC_API_KEY` | At least one* | Anthropic API key |
| `GOOGLE_API_KEY` | At least one* | Google AI API key |
| `XAI_API_KEY` | No | xAI API key (Grok models). It doesn't count toward "at least one" yet: xAI models are offered only after `uv run crucible catalog-sync` has verified them and they are added to the registry (see [Development](development.md)) |
| `NEXT_PUBLIC_API_URL` | No | Backend URL for the frontend (default `http://localhost:8000`). Read when the frontend is built, not when it starts |
| `HOST` | No | Backend bind address (default `127.0.0.1`) |
| `CORS_ORIGINS` | No | Extra browser origins, comma-separated. `localhost` / `127.0.0.1` on any port are always allowed. Also governs which pages may open the WebSockets |
| `ALLOWED_HOSTS` | No | Extra hostnames the API may be reached as, comma-separated (`*` allows any). `localhost`, `127.0.0.1` and `::1` are always allowed; other `Host` headers get a 400, which blocks DNS rebinding |
| `PORT` | No | Backend port (default `8000`) |
| `CRUCIBLE_RELOAD` | No | `0` turns off reloading on code changes (`python -m app.main` reloads by default; the Docker image sets `0`) |
| `DATABASE_PATH` | No | SQLite file for threads and checkpoints (default `backend/checkpoints.sqlite`) |
| `UPLOAD_DIR` | No | Where uploaded files are kept (default `backend/uploads`) |
| `CHROMA_DIR` | No | Vector store directory (default `backend/chroma_db`) |
| `CRUCIBLE_ALLOW_REMOTE_CONFIG` | No | Let non-loopback clients use the API-key endpoint. Docker Compose sets it, since it publishes on `127.0.0.1` only |

\* Keys can also be set at runtime in **Control Panel → API Keys**, which writes them to `backend/.env`. That endpoint only accepts requests from the local machine.

> **⚠️ The API has no authentication.** It listens on loopback by default. If you set `HOST=0.0.0.0` to reach it from another machine, anyone on that network can use your API keys. Reaching it under another name or IP also needs that name in `ALLOWED_HOSTS` (and the frontend's origin in `CORS_ORIGINS`).
>
> Browser pages from other sites are kept out: WebSockets and CORS accept only allowed origins, unknown `Host` headers are refused, and form, text or untyped `POST`s need an `X-Crucible-Client` header (which forces a CORS preflight). Scripts calling the REST API send JSON, or add that header to a multipart upload.

## Docker

`docker compose up --build` publishes the frontend on http://localhost:3000 and the API on http://localhost:8000, both on `127.0.0.1` only. Threads, uploads, the vector store and the embedding model (downloaded the first time you search your documents) persist in Docker volumes. `backend/.env` is mounted into the backend container, so keys set in the app are written back to it and survive a rebuild.

Other ports: `CRUCIBLE_BACKEND_PORT=8100 CRUCIBLE_FRONTEND_PORT=3100 docker compose up --build`. The backend's address is built into the frontend bundle, so rebuild after changing the backend port.

| Use | When |
|---|---|
| `./start_dev.sh` | Development: hot reload, fast restarts, easy debugging |
| `docker compose` | Trying it out or running it long-term: no local toolchain needed |
