# Reverse Workflow Recommendation System for Shuffle SOAR

![License](https://img.shields.io/badge/license-AGPL--3.0-blue)
![Status](https://img.shields.io/badge/status-Prototype-orange)
![Build](https://img.shields.io/badge/build-Research%20Thesis-green)

A Large Language Model-based system for automatically generating reverse workflow recommendations on the Shuffle SOAR platform. Designed to help Security Operations Centers (SOCs) efficiently rollback false positive incidents by reconstructing the inverse of automated security actions.

**Thesis**: Design and Implementation of a Reverse Workflow Recommendation System Prototype Utilizing Large Language Models on the Shuffle SOAR Platform
- Authors: Reynaldo Henelson and Samuel Chandra Sutiaman

<img width="913" height="461" alt="image" src="https://github.com/user-attachments/assets/84607fb0-38ac-4ac1-b90c-90e889a6716b" />

---

## Problem Statement

Modern SOCs rely on SOAR platforms to automate incident response through workflows that execute state-changing actions (e.g., blocking IPs on firewalls, disabling user accounts, isolating network devices). However, when alarms are confirmed as **false positives**, these automated actions must be manually reversed—a time-consuming and error-prone process.

### Key Challenges
- **No native rollback mechanism** in Shuffle SOAR for reversing executed workflows
- **Manual reconstruction** required for each false positive incident
- **High error risk** when analysts manually reverse complex multi-step actions
- **Increased Mean Time To Respond (MTTR)** due to manual workflow creation
- **Inconsistent action-reversal mapping** across different security tools and connectors

### The Gap
No existing research integrates LLMs to automatically generate reverse workflow recommendations on open-source SOAR platforms. Prior LLM-SOC research focuses on alarm triage, incident classification, or log summarization—not system recovery.

---

## Solution Overview

This prototype implements a **microservice architecture** that:

1. **Captures** the executed workflow JSON from Shuffle
2. **Parses** workflow structure into nodes, dependencies, and action parameters
3. **Stores** the workflow as a Neo4j knowledge graph
4. **Maps** actions to their reversals through a deterministic dictionary and LLM-assisted inference
5. **Generates** a draft reverse workflow in Shuffle-compatible JSON format
6. **Marks unsafe actions** as checkpoints requiring analyst review before execution

### Key Insight
The system uses a **hybrid approach**:
- **Deterministic mapping** (dictionary-based) for common action reversals (fast, reliable)
- **LLM inference** only for unmapped actions (flexible, handles edge cases)
- **Analyst validation** as the final safety gate (no auto-execution)

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                      Shuffle SOAR UI                         │
│         (Execute Reverse Workflow Button)                    │
└────────────────────────┬────────────────────────────────────┘
                         │ GET /workflow/{id}
                         ↓
┌─────────────────────────────────────────────────────────────┐
│           Reverse Workflow Service (Node.js)                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 1. Fetch Workflow JSON from Shuffle                 │   │
│  │ 2. Parse structure (nodes, edges, parameters)       │   │
│  │ 3. Call Neo4j to store/retrieve knowledge graph     │   │
│  │ 4. Call LLM Service for action mapping              │   │
│  │ 5. Validate generated reverse workflow              │   │
│  │ 6. Import back to Shuffle                           │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────┘
         │                        │                       │
         ↓                        ↓                       ↓
    ┌─────────┐            ┌─────────┐           ┌─────────────┐
    │  Neo4j  │            │ LLM Svc │           │  Shuffle    │
    │ (Graph) │            │ (Python)│           │   (SOAR)    │
    └─────────┘            └─────────┘           └─────────────┘
                                ↓
                        ┌──────────────────┐
                        │  Ollama (Qwen3)  │
                        │   8B Q5_K_M      │
                        └──────────────────┘
```

### Technology Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Orchestrator** | Node.js | 18+ | Parse workflow, coordinate LLM calls, import to Shuffle |
| **Graph Database** | Neo4j | 4.4+ | Store workflow structure and action metadata |
| **LLM Service** | Python FastAPI | 3.9+ | Expose LLM inference as HTTP API |
| **LLM Engine** | Ollama | Latest | Local inference runtime |
| **Base Model** | Qwen3 8B | Q5_K_M (quant) | Reasoning on security action reversal |
| **Relational DB** | PostgreSQL | 13+ | Action templates, app catalog (optional) |

---

## Installation & Setup

### Prerequisites

- Docker & Docker Compose
- 16GB+ RAM (for Ollama inference)
- 10GB+ disk space (for model + data)
- Shuffle SOAR instance (v1.0+)

### Quick Start

#### 1. Clone and Configure

```bash
git clone https://github.com/yourusername/reverse-workflow-system.git
cd reverse-workflow-system

# Copy environment template
cp .env.example .env

# Edit .env for your Shuffle instance
# SHUFFLE_API_URL=http://your-shuffle-instance:3001
# SHUFFLE_API_KEY=your-api-key
# OLLAMA_READ_TIMEOUT=900
```

#### 2. Launch with Docker Compose

```bash
docker compose up -d --build

# Check services are healthy
docker compose ps
```

#### 3. Verify Installation

```bash
# Check Orchestrator
curl http://localhost:5000/health

# Check LLM Service
curl http://localhost:8000/docs

# Check Neo4j
curl http://localhost:7474
```

#### 4. Load Initial Data

```bash
# Optional: Seed action templates and reverse mappings
cd services/llm-service
python scripts/init_db.sql
python scripts/ingest_playbooks.py
```

---

## Usage

### For Security Analysts

1. Open a workflow in Shuffle that you want to reverse
2. Click the **"Execute Reverse Workflow"** button (top-right corner)
3. Review the generated reverse workflow draft:
   - Green actions: Safe, automatically reversible
   - Yellow actions: Marked as checkpoints (requires review)
   - Red actions: Cannot be safely reversed
4. Modify if needed, then click **"Import to Shuffle"**
5. Execute the reverse workflow manually after confirmation

### For Developers

#### Triggering Reverse Workflow Generation

```bash
# Direct Node.js API call
curl -X POST http://localhost:5000/api/reverse-workflow \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_id": "shuffle-workflow-123",
    "shuffle_api_url": "http://shuffle:3001",
    "shuffle_api_key": "your-key"
  }'
```

**Response:**
```json
{
  "status": "success",
  "reverse_workflow_id": "rw-456",
  "workflow_json": { ... },
  "checkpoints": [
    {
      "action_id": "action-789",
      "action_name": "Block IP",
      "reason": "No safe reverse defined; manual review required"
    }
  ],
  "validation_report": {
    "structure_valid": true,
    "import_ready": true,
    "warnings": []
  }
}
```

#### Querying Knowledge Graph

```bash
# Example: Retrieve all actions in a workflow and their reversals
# Connect to Neo4j at http://localhost:7687 (Cypher console)

MATCH (w:WORKFLOW {workflow_id: "shuffle-workflow-123"})
  -[:CONTAINS]->(a:ACTION)
  -[rev:REVERSES]->(inverse:ACTION)
RETURN a.action_name, inverse.action_name, rev.confidence
```

#### Custom Action Mapping

Add new action-reversal pairs to Neo4j:

```cypher
MATCH (app:APP {app_id: "custom-app"})
CREATE (action:ACTION {
  app_id: "custom-app",
  action_name: "SendAlert",
  action_label: "Send Security Alert"
})
-[r:REVERSES]->(reverse_action:ACTION {
  app_id: "custom-app",
  action_name: "ClearAlert",
  action_label: "Clear Security Alert"
})
SET r.confidence = 0.95, r.reason = "Manual definition"
```

---

## System Architecture Details

### Stage 1: Workflow Extraction
- Fetch workflow JSON from Shuffle REST API
- Parse structure: `nodes` (actions), `edges` (dependencies), `start/end` markers
- Extract metadata: workflow name, description, trigger conditions

### Stage 2: Knowledge Graph Construction
- Create Neo4j nodes for each action with properties (app_id, parameters, conditions)
- Create edges representing execution order and data flow
- Query existing action-reversal mappings from the knowledge graph

### Stage 3: Deterministic Reversal Mapping
- For each action in the workflow:
  - Check if a dictionary entry exists for (app_id, action_name) → reverse_action
  - If found, mark as "safe" with confidence score
  - If not found, queue for LLM inference

### Stage 4: LLM-Assisted Mapping (Fallback)
- For unmapped actions, construct a detailed prompt including:
  - Action description and parameters
  - Similar actions and their known reversals from the knowledge graph
  - Security context (SOC incident response domain knowledge)
- Invoke Qwen3 8B through Ollama
- Parse LLM output to extract suggested reversal action and confidence

### Stage 5: Validation & Checkpoint Marking
- Validate reverse workflow structure (all edges resolve, no cycles)
- Check parameter compatibility (reverse action accepts same params)
- Mark actions with low confidence (<0.7) or missing reversals as checkpoints
- Generate a structured validation report

### Stage 6: Export & Import
- Convert reverse workflow to Shuffle-compatible JSON format
- Return to UI or push directly to Shuffle import endpoint
- Analyst reviews and manually triggers execution

---

## Evaluation Results

### Test Coverage

**Black-Box Testing: 10 Scenarios**
- ✅ **6 Passed**: Successfully generated and imported reverse workflows
- ❌ **4 Failed (Controlled)**: Negative tests passed as designed
  - Workflows with unmappable actions → correctly flagged checkpoints
  - Workflows with unsafe reversals → correctly blocked import
  - Malformed inputs → gracefully handled with validation errors

### User Evaluation

**Survey**: 9 Cyber Security Practitioners (SOC analysts, incident responders)

| Criterion | Average Score | Category |
|-----------|---------------|----------|
| **Usefulness** | 4.67 / 5.0 | Very Good |
| **Accuracy of Reversals** | 4.55 / 5.0 | Very Good |
| **Ease of Use** | 4.33 / 5.0 | Good |
| **Trust in System** | 4.22 / 5.0 | Good |
| **Time Saved** | 4.44 / 5.0 | Very Good |
| **Overall** | **4.55 / 5.0** | **Very Good** |

### Key Findings
- Practitioners found reverse workflow drafts "substantially reduced manual effort"
- Checkpoint marking was well-received as a safety mechanism
- LLM output quality improved significantly with action-specific context
- System should be considered a *draft recommendation tool*, not autonomous rollback

---

## Limitations & Known Issues

### Technical Limitations
1. **Deterministic Mapping Only**
   - System relies on manually defined action-reversal pairs
   - Coverage limited to pre-mapped apps/actions (~150+ common mappings included)
   - New or custom actions require Neo4j schema updates

2. **LLM Hallucination Risk**
   - Qwen3 8B may suggest non-existent action parameters
   - Solutions: Validator checks against action schema, analyst review, low-confidence checkpoint marking

3. **Parameter Transformation**
   - Some actions require transformed parameters for reversal (e.g., "BlockIP" → "AllowIP" requires IP set transformation)
   - Not all parameter mappings are automated; complex transformations marked as checkpoints

4. **State-Dependent Actions**
   - Actions that depend on external state (e.g., "Delete file if not backed up") may fail reversals
   - No built-in state tracking across workflow execution

5. **Timeout on CPU Inference**
   - Qwen3 8B on CPU takes 5–15 minutes for complex prompts
   - Set `OLLAMA_READ_TIMEOUT=900` (15 minutes) for safety
   - GPU acceleration recommended for production use

### Known Issues
- [ ] Edge case: Multi-step action reversals (actions requiring multiple inverse steps)
- [ ] Neo4j query performance with >10,000 workflow nodes (optimize with indexes)
- [ ] Shuffle API compatibility with older versions (<v1.0)

### Recommended Improvements
1. **GPU Support**: Deploy with NVIDIA GPU for 10x faster inference
2. **Caching**: Store computed action reversals to avoid re-querying LLM
3. **User Feedback Loop**: Allow analysts to rate reversal quality → retrain LLM or update mappings
4. **Action Schema Validation**: Stricter parameter type checking before import
5. **Batch Processing**: Support bulk reverse workflow generation for large incidents

---

## Configuration

### Environment Variables

```bash
# Shuffle Integration
SHUFFLE_API_URL=http://shuffle:3001
SHUFFLE_API_KEY=your-shuffle-api-key
SHUFFLE_VERIFY_SSL=false  # Only for dev/test

# Node.js Orchestrator
NODE_ENV=production
ORCHESTRATOR_PORT=5000
ORCHESTRATOR_LOG_LEVEL=info

# Neo4j Knowledge Graph
NEO4J_URI=neo4j://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-neo4j-password

# LLM Service (Python)
LLM_SERVICE_URL=http://llm-service:8000
OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=qwen3:8b-q5_k_m  # Quantized for RAM efficiency
OLLAMA_READ_TIMEOUT=900  # 15 minutes for CPU inference
LLM_TEMPERATURE=0.1  # Lower = more deterministic
LLM_MAX_RETRIES=3

# PostgreSQL (optional, for action templates)
POSTGRES_HOST=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-postgres-password
POSTGRES_DB=reverse_workflow

# Security
API_JWT_SECRET=your-jwt-secret
CORS_ALLOWED_ORIGINS=http://localhost:3000

# Monitoring (optional)
PROMETHEUS_PORT=9090
```

### Docker Compose Overrides

For production deployments with GPU:

```yaml
# docker-compose.override.yml
services:
  ollama:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      OLLAMA_GPU: "1"  # Enable GPU acceleration
```

---

## API Reference

### Reverse Workflow Endpoints

#### POST `/api/reverse-workflow`
Generate a reverse workflow from a Shuffle workflow.

**Request:**
```json
{
  "workflow_id": "string (required)",
  "shuffle_api_url": "string (optional, uses env default)",
  "shuffle_api_key": "string (optional, uses env default)",
  "use_llm_fallback": boolean (default: true),
  "force_refresh": boolean (default: false)
}
```

**Response (200):**
```json
{
  "status": "success",
  "reverse_workflow_id": "rw-uuid",
  "workflow_json": { ... },
  "checkpoints": [ ... ],
  "validation_report": { ... }
}
```

#### GET `/api/reverse-workflow/{id}`
Retrieve a previously generated reverse workflow.

#### GET `/health`
Health check endpoint.

### LLM Service Endpoints

#### POST `/api/v1/generate/playbook`
(Python service) Generate reverse workflow recommendations.

#### GET `/docs`
OpenAPI/Swagger documentation for LLM Service.

---

## Testing

### Run Unit Tests
```bash
cd services/reverse-workflow-service
npm test
```

### Run Integration Tests
```bash
cd services/llm-service
pytest tests/ -v
```

### Black-Box Testing Scenarios

```bash
# Test 1: Simple linear workflow reversal
# Test 2: Workflow with conditional branching
# Test 3: Workflow with loop structures
# Test 4: Unmapped actions (LLM fallback)
# Test 5: Malformed workflow JSON (error handling)
# ... (10 total test scenarios)

./tests/black-box/run_scenarios.sh
```

---

## Contributing

This is a **research prototype**, not production-ready software. Contributions are welcome for:

- Action-reversal mappings (adding more coverage)
- Prompt engineering improvements (better LLM reasoning)
- Performance optimizations (Neo4j indexing, caching)
- Bug reports and issue tracking
- Documentation improvements

Please see `CONTRIBUTING.md` for guidelines.

---

## Security Considerations

⚠️ **Critical Warnings**

1. **No Auto-Execution**: All reverse workflows are draft recommendations. Manual analyst review is **mandatory** before execution.
2. **LLM Limitations**: The system may generate plausible-sounding but incorrect action reversals. Hallucination risk is mitigated by:
   - Checkpoint marking for low-confidence outputs
   - Mandatory analyst review before import
   - Validation against Shuffle action schema
3. **Data Sensitivity**: Shuffle workflows may contain sensitive incident details. Consider:
   - Running the system on-premises (no cloud LLM services)
   - Implementing API authentication and authorization
   - Logging/auditing all reverse workflow generation
4. **Parameter Transformation**: Reversal parameters may require transformation (e.g., IP blocklist → allowlist). Verify transformations manually.

### Compliance
- **GDPR**: No personal data sent to external LLM services (Ollama runs locally)
- **HIPAA**: On-premises deployment supported
- **SOC 2**: Audit logging available; see `monitoring/audit.log`

---

## References & Citations

### Key Publications
1. **Incident Response & SOAR**
   - NIST Cybersecurity Framework (SP 800-61)
   - Gartner SOAR Platform Reviews
   - Academic studies on automation in incident response

2. **Large Language Models in Cybersecurity**
   - "Leveraging LLMs for Security Event Triage" (related work)
   - Prompting best practices for technical domains

3. **Knowledge Graphs & Neo4j**
   - Neo4j documentation for workflow modeling
   - Knowledge graph applications in security

4. **The Shuffle Platform**
   - Shuffle SOAR GitHub repository
   - Official API documentation

---

## License

- **Backend (Node.js, Python services)**: AGPLv3
- **Frontend UI components**: MIT
- **Documentation**: CC-BY-4.0
- **Action mappings & datasets**: Provided as-is for research use

Redistribution of modified versions requires attribution and license disclosure.

---

## Authors & Acknowledgments

**Research Team**
- Reynaldo Henelson
- Samuel Chandra Sutiaman 

**Advisor**
- Dr. Aditya Kurniawan, S.Kom., MMSI., CND, CEHmaster

**Institution**
- Bina Nusantara University, School of Computer Science
- Cyber Security Program

**Special Thanks**
- Shuffle SOAR project and community
- Ollama project for local inference capabilities
- Neo4j for graph database platform

---

## Disclaimer

This is a **research prototype** developed as part of an academic thesis. It is provided "as-is" without warranty. Users assume all responsibility for:
- Validating generated reverse workflows before execution
- Data loss or system misconfiguration
- Compliance with their organization's security policies and change management procedures

**Never execute auto-generated reverse workflows without analyst review.**
