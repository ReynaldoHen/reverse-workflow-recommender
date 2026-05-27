"""
AI Playbook Recommender v1.1 - FastAPI service.

Improvements over v1.0:
  - Knowledge base RAG (runbooks/SOPs/policies/MITRE notes)
  - Hybrid search (vector + BM25 with Reciprocal Rank Fusion)
  - Past-incident retrieval for "we've seen this before" context
  - Strict cite-or-omit grounding with schema validation
  - Confidence threshold to drop low-conviction reranks
"""

import os
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from llm_client import get_client
from retrieval import (hybrid_search_playbooks, hybrid_search_kb,
                       similar_incidents)
from grounding import build_grounded_prompt, parse_strict

PG_DSN = os.environ["PG_DSN"]
TOP_K = int(os.environ.get("TOP_K", "5"))
KB_TOP_K = int(os.environ.get("KB_TOP_K", "4"))
INC_TOP_K = int(os.environ.get("INC_TOP_K", "3"))
EMBED_DIM = int(os.environ.get("EMBED_DIM", "768"))

app = FastAPI(title="Shuffle Playbook Recommender v1.1")
llm = get_client()


def _conn():
    return psycopg2.connect(PG_DSN)


class Playbook(BaseModel):
    workflow_id: str
    name: str
    description: str = ""
    trigger_type: str = ""
    mitre_tags: list[str] = Field(default_factory=list)
    apps_used: list[str] = Field(default_factory=list)
    alert_category: str = ""


class KnowledgeDoc(BaseModel):
    doc_type: str
    title: str
    source_uri: str = ""
    chunk_index: int = 0
    content: str
    tags: list[str] = Field(default_factory=list)
    mitre_tags: list[str] = Field(default_factory=list)


class Incident(BaseModel):
    incident_id: str
    title: str
    summary: str = ""
    iocs: list[str] = Field(default_factory=list)
    mitre_tags: list[str] = Field(default_factory=list)
    workflow_used: str = ""
    outcome: str


class Alert(BaseModel):
    alert_id: str
    title: str
    description: str = ""
    severity: str = ""
    mitre_technique: str = ""
    affected_assets: list[str] = Field(default_factory=list)
    iocs: list[str] = Field(default_factory=list)


class Feedback(BaseModel):
    alert_id: str
    workflow_id: str
    rank: int
    decision: str


def _check_dim(vec):
    if len(vec) != EMBED_DIM:
        raise HTTPException(500, f"Embedding dim {len(vec)} != {EMBED_DIM}")


@app.post("/index")
def index_playbook(pb: Playbook):
    doc = (f"{pb.name}. {pb.description}. Trigger: {pb.trigger_type}. "
           f"MITRE: {' '.join(pb.mitre_tags)}. Apps: {' '.join(pb.apps_used)}. "
           f"Category: {pb.alert_category}")
    vec = llm.embed(doc)
    _check_dim(vec)
    conn = _conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO playbook_embedding
                  (workflow_id, name, description, trigger_type, mitre_tags,
                   apps_used, alert_category, embedding, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (workflow_id) DO UPDATE SET
                  name=EXCLUDED.name, description=EXCLUDED.description,
                  trigger_type=EXCLUDED.trigger_type,
                  mitre_tags=EXCLUDED.mitre_tags, apps_used=EXCLUDED.apps_used,
                  alert_category=EXCLUDED.alert_category,
                  embedding=EXCLUDED.embedding, updated_at=now()
                """,
                (pb.workflow_id, pb.name, pb.description, pb.trigger_type,
                 pb.mitre_tags, pb.apps_used, pb.alert_category, vec),
            )
    finally:
        conn.close()
    return {"indexed": pb.workflow_id}


@app.post("/index_knowledge")
def index_knowledge(doc: KnowledgeDoc):
    """Index a runbook, SOP, policy, or any text reference for RAG."""
    doc_text = f"{doc.title}\n\n{doc.content}"
    vec = llm.embed(doc_text)
    _check_dim(vec)
    conn = _conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_base
                  (doc_type, title, source_uri, chunk_index, content,
                   tags, mitre_tags, embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING doc_id
                """,
                (doc.doc_type, doc.title, doc.source_uri, doc.chunk_index,
                 doc.content, doc.tags, doc.mitre_tags, vec),
            )
            doc_id = cur.fetchone()[0]
    finally:
        conn.close()
    return {"indexed": str(doc_id), "doc_type": doc.doc_type}


@app.post("/index_incident")
def index_incident(inc: Incident):
    """Index a closed incident so future similar alerts get historical context."""
    doc = (f"{inc.title}. {inc.summary}. "
           f"IOCs: {' '.join(inc.iocs)}. MITRE: {' '.join(inc.mitre_tags)}. "
           f"Outcome: {inc.outcome}")
    vec = llm.embed(doc)
    _check_dim(vec)
    conn = _conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO incident_history
                  (incident_id, title, summary, iocs, mitre_tags,
                   workflow_used, outcome, embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (incident_id) DO UPDATE SET
                  title=EXCLUDED.title, summary=EXCLUDED.summary,
                  iocs=EXCLUDED.iocs, mitre_tags=EXCLUDED.mitre_tags,
                  workflow_used=EXCLUDED.workflow_used,
                  outcome=EXCLUDED.outcome, embedding=EXCLUDED.embedding
                """,
                (inc.incident_id, inc.title, inc.summary, inc.iocs,
                 inc.mitre_tags, inc.workflow_used, inc.outcome, vec),
            )
    finally:
        conn.close()
    return {"indexed": inc.incident_id, "outcome": inc.outcome}


@app.post("/recommend")
def recommend(alert: Alert):
    """Hybrid retrieval over playbooks + KB + incidents, then grounded rerank."""
    query = (f"{alert.title}. {alert.description}. "
             f"Severity: {alert.severity}. "
             f"MITRE: {alert.mitre_technique}. "
             f"IOCs: {' '.join(alert.iocs)}")
    qvec = llm.embed(query)

    conn = _conn()
    try:
        candidates = hybrid_search_playbooks(conn, qvec, query, TOP_K)
        kb_chunks = hybrid_search_kb(conn, qvec, query, KB_TOP_K)
        incidents = similar_incidents(conn, qvec, INC_TOP_K)
    finally:
        conn.close()

    if not candidates:
        return {"recommendations": [], "note": "no playbooks indexed"}

    cand_dicts = [dict(c) for c in candidates]
    kb_dicts = [dict(k) for k in kb_chunks]
    inc_dicts = [dict(i) for i in incidents]

    prompt, valid_ids = build_grounded_prompt(
        query, cand_dicts, kb_dicts, inc_dicts,
    )

    raw = llm.rerank(prompt)
    ranked = parse_strict(raw, valid_ids, len(cand_dicts))

    if not ranked:
        out = [{
            "workflow_id": c["workflow_id"],
            "name": c["name"],
            "similarity": round(float(c.get("similarity", 0) or 0), 4),
            "success_count": c.get("success_count", 0),
            "reject_count": c.get("reject_count", 0),
            "confidence": None,
            "evidence_id": None,
            "reason": "vector similarity (no grounded rerank available)",
            "grounded": False,
        } for c in cand_dicts]
        return {
            "alert_id": alert.alert_id,
            "recommendations": out,
            "grounded": False,
            "note": "rerank discarded by guardrails; returning vector order",
        }

    out = []
    for item in ranked:
        c = cand_dicts[item.candidate_index - 1]
        out.append({
            "workflow_id": c["workflow_id"],
            "name": c["name"],
            "similarity": round(float(c.get("similarity", 0) or 0), 4),
            "success_count": c.get("success_count", 0),
            "reject_count": c.get("reject_count", 0),
            "confidence": item.confidence,
            "evidence_id": item.evidence_id,
            "reason": item.reason,
            "grounded": True,
        })

    return {
        "alert_id": alert.alert_id,
        "recommendations": out,
        "grounded": True,
        "evidence_sources": {
            "playbooks": len(cand_dicts),
            "knowledge_chunks": len(kb_dicts),
            "incidents": len(inc_dicts),
        },
    }


@app.post("/feedback")
def feedback(fb: Feedback):
    if fb.decision not in ("accepted", "rejected"):
        raise HTTPException(400, "decision must be accepted|rejected")
    conn = _conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO recommendation_feedback
                   (alert_id, workflow_id, rank, decision)
                   VALUES (%s,%s,%s,%s)""",
                (fb.alert_id, fb.workflow_id, fb.rank, fb.decision),
            )
    finally:
        conn.close()
    return {"recorded": True}


@app.get("/health")
def health():
    try:
        _ = llm.embed("ping")
        llm_ok = True
    except Exception as exc:
        return {"status": "degraded", "llm_error": str(exc)}
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT 1")
        db_ok = True
    except Exception as exc:
        return {"status": "degraded", "db_error": str(exc), "llm_ok": llm_ok}
    return {"status": "ok", "llm_ok": llm_ok, "db_ok": db_ok, "version": "1.1"}
