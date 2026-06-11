# AI Playbook Recommender — Shuffle SOAR

Hybrid RAG + Semi-Agentic recommendation system that surfaces the right Shuffle workflows for any SOC task.

## Architecture

```
Analyst Query
     │
     ▼
Intent Classifier (Llama 3.1 8B)
     │
     ▼
Hybrid Retrieval
  ├─ Semantic search   (BGE-M3 → Qdrant)        weight: 0.5
  ├─ Keyword search    (BM25 → PostgreSQL)        weight: 0.2
  └─ Metadata scoring  (integration overlap)      weight: 0.3
     │
     ▼
BGE Reranker (cross-encoder, top 5)
     │
     ▼
LLM Recommendation (Llama 3.1 8B, structured JSON)
     │
     ▼ (if use_refinement=true)
Semi-Agentic Refinement
  ├─ verify_integration_compatibility()
  ├─ check_required_customizations()
  └─ flag_config_gaps()
     │
     ▼
Response: top 3 playbooks + confidence scores + reasoning
```

## Prerequisites

- Docker + Docker Compose
- 8 GB RAM minimum (16 GB recommended for GPU)
- 20 GB disk (models + data)

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env with your settings (at minimum change SECRET_KEY)

# 2. Start all services
docker compose up -d

# 3. Pull the LLM model (one-time, ~5 GB)
docker exec playbook-ollama ollama pull llama3.1:8b

# 4. Ingest sample playbooks
python scripts/ingest_playbooks.py \
  --api-url http://localhost:8000 \
  --api-key <key from startup logs>

# 5. Open the UI
open http://localhost:8080
```

The API key is printed in the `playbook-api` container logs on first startup:
```bash
docker logs playbook-api | grep "Default admin created"
```

## Services

| Service      | URL                         | Purpose                          |
|--------------|-----------------------------|----------------------------------|
| UI           | http://localhost:8080        | Analyst web interface            |
| API          | http://localhost:8000        | FastAPI backend                  |
| API Docs     | http://localhost:8000/docs   | Swagger UI                       |
| Grafana      | http://localhost:3000        | Dashboards (admin/admin)         |
| Prometheus   | http://localhost:9090        | Metrics                          |
| Qdrant       | http://localhost:6333        | Vector DB admin                  |

## API Usage

### Authenticate
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'
```

### Simple Recommendation
```bash
curl -X POST http://localhost:8000/api/v1/recommend \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "I need to triage phishing emails with Microsoft Sentinel",
    "top_k": 3
  }'
```

### With Semi-Agentic Refinement
```bash
curl -X POST http://localhost:8000/api/v1/recommend \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Phishing investigation with Sentinel",
    "use_refinement": true,
    "analyst_context": {
      "available_integrations": ["Microsoft Sentinel", "Slack"],
      "api_keys_configured": ["Slack"]
    }
  }'
```

### Ingest a Custom Playbook
```bash
curl -X POST http://localhost:8000/api/v1/playbooks \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Custom Playbook",
    "description": "...",
    "integrations": ["Splunk", "Jira"],
    "category": "Alert Triage",
    "use_cases": ["custom alert handling"]
  }'
```

## Shuffle SOAR Integration

### Option A: Shuffle App (Recommended)
1. In Shuffle, go to **Apps** → **New App**
2. Upload `shuffle_app/api.yaml`
3. Set authentication: **API Key** = your `X-API-Key`
4. Set `RECOMMENDER_API_URL` = the URL of your deployed API
5. Use the `recommend_playbook` action in any workflow

### Option B: HTTP action in Shuffle workflow
```
POST http://your-api:8000/api/v1/recommend
Headers: X-API-Key: <your-key>
Body: {"query": "$exec.input.query", "use_refinement": false}
```

## Configuration

Key `.env` settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (change this!) | JWT signing key |
| `OLLAMA_MODEL` | `llama3.1:8b` | LLM model name |
| `SHUFFLE_API_URL` | empty | Your Shuffle instance URL |
| `SHUFFLE_API_KEY` | empty | Shuffle API key for sync |
| `SEMANTIC_WEIGHT` | 0.5 | Retrieval weight tuning |
| `METADATA_WEIGHT` | 0.3 | Retrieval weight tuning |
| `KEYWORD_WEIGHT` | 0.2 | Retrieval weight tuning |

## Retrieval Weight Tuning

After ingesting playbooks, run ablation studies to tune `w1/w2/w3`:

1. Create test queries in `sample_data/eval_queries.json`
2. Call `/api/v1/search` with known expected playbook IDs
3. Measure Recall@5 at different weight combinations
4. Update `.env` with the best weights found

## Monitoring

- **Grafana** at `localhost:3000` — import dashboard from `monitoring/`
- Key metrics: `recommendation_latency_seconds`, `http_requests_total`
- Alert thresholds set in `monitoring/prometheus.yml`

## Project Structure

```
ai-playbook-recommender/
├── api/                  FastAPI backend
│   ├── main.py           App entrypoint, startup
│   ├── auth.py           JWT + API key auth
│   ├── database.py       SQLAlchemy models
│   ├── schemas.py        Pydantic request/response schemas
│   ├── routes/           API route handlers
│   └── services/
│       ├── embedder.py       BGE-M3 embeddings
│       ├── retrieval.py      Hybrid search (Qdrant + PostgreSQL)
│       ├── reranker.py       BGE cross-encoder reranker
│       ├── llm.py            Ollama LLM client
│       ├── recommendation.py Core recommendation pipeline
│       ├── semi_agentic.py   Semi-agentic refinement agent
│       └── shuffle_sync.py   Shuffle API sync job
├── shuffle_app/          Custom Shuffle SOAR App
├── scripts/              DB init, ingestion scripts
├── monitoring/           Prometheus config
├── sample_data/          15 sample Shuffle playbooks
├── ui/                   Analyst web UI
└── docker-compose.yml
```

## Default Credentials

| Service | Username | Password |
|---------|----------|----------|
| App | admin | admin |
| Grafana | admin | admin |

**Change these in production.**
