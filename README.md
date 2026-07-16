# AI Gateway & Client (Omni AI)

A robust, self-hosted, invite-only multi-provider AI Gateway and client application. It supports Groq, Google Gemini, OpenRouter, Pollinations, HuggingFace Inference, DeepSeek, and local Ollama integrations, equipped with automated circuit breakers, fallback failovers, and model registry capabilities.

## Quick-Start Guide

Get the gateway and web client running locally in under 5 minutes:

### 1. Configure the Environment
Copy the `.env.example` template to `.env`:
```bash
cp .env.example .env
```
Open `.env` in your editor and fill in the following:
* **`JWT_SECRET`**: Generate a secure 32-byte secret using `openssl rand -hex 32` or type a strong custom secret.
* **`MASTER_ENCRYPTION_KEY`**: **Leave this blank** on first start. The gateway automatically generates one, appends it to your `.env`, and outputs a warning message instructing you to back it up.
* **`ADMIN_EMAIL`**: The email address for the initial administrative account (e.g. `admin@example.com`).
* **`ADMIN_BOOTSTRAP_PASSWORD`**: A temporary password for the admin account (e.g., `AdminPasswordChangeMe123!`).

### 2. Start the Application Network
Spin up the backend gateway and frontend web server via Docker Compose:
```bash
docker compose up -d --build
```
This automatically runs database migrations (`alembic upgrade head`) and starts two services:
* **Gateway API**: Runs on `http://localhost:8000`
* **Web Client**: Runs on `http://localhost:3000`

### 3. Log In & Verify
1. Open your browser and navigate to `http://localhost:3000`.
2. Log in using your configured **`ADMIN_EMAIL`** and **`ADMIN_BOOTSTRAP_PASSWORD`**.
3. **Change your password immediately** after logging in by going to Settings.
4. Onboard your first provider key (e.g., Groq or Gemini API) in **Settings**. The gateway will verify the credentials, auto-discover supported models, and benchmark latencies.
5. Go to the **Chat** tab, select a model, and send a message!

---

## Folder Structure

* `/backend` — FastAPI application containing provider adapters, routing/fallback engine, token-at-rest encryption pipelines, and tests.
* `/frontend` — SvelteKit static PWA application styled with TailwindCSS (v4) and configured with an offline-capable Service Worker.
