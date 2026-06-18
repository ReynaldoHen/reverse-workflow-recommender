# Reverse Workflow Platform

A SOAR-workflow reversal system for Shuffle, assembled as one Docker-runnable
stack. Given a Shuffle workflow, it builds a graph of it, uses an LLM (grounded
in a live catalog of Shuffle's real apps/actions) to propose a reversed/rebuilt
workflow, validates that output rigorously, and imports it back into Shuffle.

## Services

| Service | Tech | Port | Role |
|---|---|---|---|
| `reverse-workflow-service` | Node.js / Express | 5005 | Orchestrator: parses the workflow, builds the graph, talks to Neo4j/Postgres, calls the LLM service, validates the result, and imports it back into Shuffle. |
| `llm-service` | Python / FastAPI | 8000 | LLM + RAG. Queries Neo4j for graph context, retrieves similar playbooks from Qdrant, prompts Ollama, and returns the raw generated workflow. |
| `neo4j` | Graph DB | 7474 / 7687 | Knowledge graph of workflows / actions / apps; also used for semantic validation. |
| `postgres` | Relational DB | 5432 | Shared store. Orchestrator mirrors the app catalog here; the LLM service stores playbooks / generated workflows here. |
| `qdrant` | Vector DB | 6333 | Vector store for RAG retrieval. |
| `ollama` | Model runtime | 11434 | Runs the local LLM (default `llama3.1:8b`). |

## Request flow

```
Shuffle ──POST /api/reverse-workflow──▶ reverse-workflow-service (Node)
   1. parse workflow            (parsers/workflowParser.js)
   2. build graph               (graph/graphBuilder.js)
   3. save graph → Neo4j        (neo4j/saveGraph.js)
   4. sync app catalog          (shuffleApps/* → Neo4j + Postgres)
   5. confirm Neo4j context     (neo4j/queryWorkflowContext.js)
   6. login + call LLM ─────────▶ llm-service  POST /api/v1/generate/reverse
        (Node sends workflow_id/workflow_name/retry_context + JWT;
         Python reads the graph back from Neo4j, does RAG, prompts Ollama)
   7. validate + retry ×3        (validators/validateWorkflow.js)
   8. import back → Shuffle      (builders/buildShuffleWorkflow.js)
◀── { generated_workflow_id, ... }
```

## Quick start

```bash
cp .env.example .env          # then edit the secrets (Postgres/Neo4j passwords, LLM_SECRET_KEY)
docker compose up -d --build  # or: make up
docker compose exec ollama ollama pull llama3.1:8b   # or: make pull-model
```

Then check health:

```bash
curl http://localhost:8000/health     # llm-service  → {"status":"ok", ...}
curl http://localhost:5005/           # orchestrator → "Reverse Workflow Service Running"
```

The first `up` builds images and the LLM service downloads embedding/reranker
models on first boot — give it a few minutes. The model pull (~5 GB) is a
one-time step stored in the `ollama_models` volume.

## How the two services authenticate

The Python `/generate/reverse` endpoint is JWT-protected. The orchestrator logs
in automatically at `/api/v1/auth/login` using `LLM_AUTH_USER` / `LLM_AUTH_PASS`
(default `admin` / `admin`, defined in the LLM service's `api/auth.py`), caches
the token, and re-authenticates on a 401. Change those defaults for anything
beyond local use.

## Connecting to Shuffle

For a real end-to-end run you need a reachable Shuffle instance:

- Set `SHUFFLE_API_URL` and `SHUFFLE_API_KEY` in `.env`. The key needs
  permission to read apps and create workflows.
- Trigger a reversal by POSTing a workflow to the orchestrator:

```bash
curl -X POST http://localhost:5005/api/reverse-workflow \
  -H "Content-Type: application/json" \
  -d '{ "workflow_id": "...", "workflow_name": "...", "actions": [...], "branches": [...] }'
```

Without Shuffle configured, the stack still starts: the catalog sync no-ops and
the LLM service runs in offline mode, but a full reversal needs the catalog and
the import-back step, so connect Shuffle before expecting end-to-end results.

## Data stores share one Postgres

Both services point at the same Postgres instance with the same credentials.
Their tables don't collide:

- Orchestrator: `app_catalog`, `action_templates`, `parameter_templates`.
- LLM service: `playbooks`, `generated_workflows`, `feedback` (created from
  `services/llm-service/scripts/init_db.sql`, also auto-created by SQLAlchemy).

## Make targets

```
make up          build & start everything
make pull-model  pull the LLM model into Ollama (MODEL=llama3.1:8b)
make health      curl both health endpoints
make logs        tail all logs
make down        stop the stack
make clean       stop and remove volumes (DESTROYS DATA)
```

## Security notes

- Rotate the previously-exposed Neo4j credential if this came from the earlier
  codebase — it was scrubbed from source, but that does not undo its exposure.
- Change `LLM_SECRET_KEY`, the Postgres/Neo4j passwords, and the
  `LLM_AUTH_USER` / `LLM_AUTH_PASS` defaults before any non-local deployment.
- `.env` holds all secrets and must never be committed.

## Per-service docs

- `services/reverse-workflow-service/` — Node orchestrator.
- `services/llm-service/README.md` — Python LLM + RAG service details.
```
