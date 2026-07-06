# AI Playbook Recommender for Shuffle SOAR

An offline-capable AI assistant for SOC analysts. It **recommends** the right
Shuffle SOAR playbook for a situation, **explains** the playbook's steps in plain
language, and — when it cannot generate (reverse) a workflow or hits an error —
**recommends a concrete next-best action** instead of failing silently.

The system connects to Shuffle over its API. With no credentials it runs in an
offline/mock mode so the thesis demo works end to end.

## Capabilities
1. **Recommend (forward)** — query → ranked playbooks with confidence scores.
2. **Explain** — plain-language "what / why" for each step of a playbook.
3. **Generate (reverse, best-effort)** — natural language → Shuffle workflow JSON.
4. **Action Recommender (fallback)** — fires when reverse generation is not
   possible or any error occurs; returns prioritised analyst actions.
5. **Shuffle integration** — live API client + background sync, graceful offline mode.

## Quick start
```bash
cp .env.example .env          # set SECRET_KEY + POSTGRES_PASSWORD
docker compose up -d          # core stack (add --profile monitoring for Prometheus/Grafana)
docker compose exec ollama ollama pull dengcao/Qwen3-8B:Q5_K_M
```
Open the UI at http://localhost:8080 (login `admin` / `admin`).

## Connecting to Shuffle
Set `SHUFFLE_API_URL` and `SHUFFLE_API_KEY` in `.env`. The app registry then syncs
the apps actually installed in your Shuffle instance, and generated workflows can
be deployed with `deploy_to_shuffle=true`.

## Layout
`api/` FastAPI service · `sample_data/` 30-playbook dataset · `scripts/` DB + ingest ·
`ui/` analyst console · `shuffle_app/` optional Shuffle custom app · `monitoring/` Prometheus.
