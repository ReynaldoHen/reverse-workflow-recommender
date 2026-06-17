"""Reverse pipeline: NL description -> LLM intermediate JSON -> Shuffle JSON.

If generation is not possible (no valid workflow after retries / no usable apps)
or any error occurs, the caller is expected to invoke the Action Recommender.
This module signals that by returning success=False with an error reason.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from neo4j import AsyncGraphDatabase

from ..config import settings, get_settings
settings = get_settings()
from .llm import llm                          # Ollama client
from .shuffle_translator import shuffle_translator
from .app_registry import app_registry
from . import retrieval                       # Hybrid search (BGE-M3 + reranker)
from .graph_retrieval import graph_retrieval

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# FORWARD PIPELINE — system prompt
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM = (
    "You design SOAR workflows. Convert the analyst's description into an "
    "intermediate workflow JSON. Respond ONLY with JSON of the form: "
    '{"name": str, "start": "n1", "nodes": [{"id": "n1", "app": "virustotal", '
    '"action": "lookup_url", "parameters": {"url": "${url}"}}], '
    '"edges": [{"from": "n1", "to": "n2", "conditions": []}]}. '
    "Use only app keys from the provided registry list."
)


# ─────────────────────────────────────────────────────────────────────────────
# FORWARD PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

class PlaybookGenerator:
    async def generate(self, description: str, target_integrations: list[str] | None = None) -> dict:
        registry_keys = [a["name"] for a in app_registry.all()]
        prompt = json.dumps({
            "description": description,
            "preferred_apps": target_integrations or [],
            "available_app_keys": registry_keys,
        })
        try:
            intermediate = await llm.complete_json(prompt, system=SYSTEM)
        except Exception as exc:
            return {"success": False, "error": f"LLM could not produce valid workflow JSON: {exc}"}

        errors = shuffle_translator.validate_intermediate(intermediate)
        if errors:
            return {"success": False, "error": "Intermediate validation failed: " + "; ".join(errors),
                    "intermediate": intermediate}

        # If no node maps to a known app, treat generation as not possible.
        known = [n for n in intermediate.get("nodes", [])
                 if not app_registry.resolve(n.get("app")).get("_synthetic")]
        if not known:
            return {"success": False,
                    "error": "No requested integrations are available in the app registry.",
                    "intermediate": intermediate}

        shuffle_wf = shuffle_translator.translate(intermediate)
        wf_errors = shuffle_translator.validate_shuffle(shuffle_wf)
        if wf_errors:
            return {"success": False, "error": "Shuffle validation failed: " + "; ".join(wf_errors),
                    "intermediate": intermediate}

        return {"success": True, "intermediate": intermediate, "shuffle_workflow": shuffle_wf}


playbook_generator = PlaybookGenerator()


# ─────────────────────────────────────────────────────────────────────────────
# REVERSE PIPELINE — helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_workflow_graph(workflow_id: str) -> List[Dict[str, Any]]:
    """
    Query Neo4j untuk Action nodes yang disimpan oleh Node.js di Step 4.

    Node.js graphBuilder.js membuat:
      (:Action {workflow_id, id, name, app_name, app_id, app_version, large_image, position})
      -[:CONNECTS_TO {condition}]->(:Action)
    """
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=settings.neo4j_auth,   # property: (neo4j_username, neo4j_password)
    )
    query = """
        MATCH (w:Workflow {id: $workflow_id})-[:CONTAINS]->(a:Action)
        OPTIONAL MATCH (a)-[r:CONNECTS_TO]->(b:Action)
        RETURN
            a.id AS id,
            a.name AS name,
            a.app_name AS app_name,
            a.app_id AS app_id,
            a.app_version AS app_version,
            a.large_image AS large_image,
            a.description AS description,
            collect({
                rel_type: type(r),
                target_id: b.id,
                target_name: b.name,
                condition: r.condition
            }) AS transitions
        ORDER BY a.position
    """
    async with driver.session() as session:
        result = await session.run(query, workflow_id=workflow_id)
        records = [record.data() async for record in result]

    await driver.aclose()

    if not records:
        raise ValueError(
            f"No Action nodes found in Neo4j for workflow_id={workflow_id}. "
            "Pastikan Step 4 (saveGraphToNeo4j) sudah berjalan."
        )

    # Hapus transition entry kosong dari OPTIONAL MATCH
    for rec in records:
        rec["transitions"] = [
            t for t in rec.get("transitions", [])
            if t.get("target_id") is not None
        ]

    return records


def _build_reverse_system_prompt(
    graph_records: List[Dict[str, Any]],
    rag_examples: List[str],
    retry_context: Optional[Any],
    graph_context: List[Dict[str, Any]] = None,
) -> str:
    """Bangun system prompt untuk Ollama: graph context + RAG examples + retry errors."""

    # ── Graph summary ──────────────────────────────────────────────────────
    graph_lines = []
    for i, action in enumerate(graph_records):
        transitions_str = ", ".join(
            f"{t['target_name']} (cond: {t['condition'] or 'always'})"
            for t in action.get("transitions", [])
        ) or "(terminal — no outgoing transitions)"

        graph_lines.append(
            f"  [{i+1}] name={action['name']}"
            f" | app={action['app_name']} v{action['app_version']}"
            f" | id={action['id']}"
            f" | large_image={action['large_image'] or ''}"
            f" | next → {transitions_str}"
        )

    graph_section = "SOURCE WORKFLOW GRAPH (dari Neo4j):\n" + "\n".join(graph_lines)

    # ── RAG examples ────────────────────────────────────────────────────────
    rag_section = (
        "SIMILAR PLAYBOOK EXAMPLES (gunakan sebagai referensi format):\n"
        + "\n---\n".join(rag_examples[:2])
        if rag_examples
        else "SIMILAR PLAYBOOK EXAMPLES: tidak tersedia."
    )

    # ── Retry error section ─────────────────────────────────────────────────
    retry_section = ""
    if retry_context and not retry_context.valid:
        error_lines = "\n".join(
            f"  • [{e.code}] di {e.location}: {e.message}"
            for e in retry_context.errors
        )
        retry_section = (
            f"\n\nATTEMPT SEBELUMNYA GAGAL (attempt {retry_context.attempt}).\n"
            f"Perbaiki SEMUA error berikut sebelum menjawab:\n{error_lines}\n"
            + (f"HINT: {retry_context.correction_instructions}"
               if retry_context.correction_instructions else "")
        )

    return f"""You are a SOAR (Security Orchestration, Automation and Response) Workflow Engineer.

TASK: Generate a REVERSE workflow JSON for the Shuffle SOAR platform.
A reverse workflow mirrors the source workflow's actions but inverts the flow direction,
creating a complementary response or rollback playbook.

OUTPUT FORMAT: return ONLY a valid JSON object — no markdown, no explanation, no code fences.
Schema yang wajib diikuti:
{{
  "name": "<string>",
  "description": "<string>",
  "start": "<id_action_pertama>",
  "actions": [
    {{
      "id": "<uuid_baru>",
      "name": "<string>",
      "app_name": "<string>",
      "app_id": "<string>",
      "app_version": "<string>",
      "large_image": "<string>",
      "label": "<string>",
      "parameters": [{{"name": "<string>", "value": "<string>"}}],
      "position": {{"x": <number>, "y": <number>}}
    }}
  ],
  "branches": [
    {{
      "id": "<uuid_baru>",
      "source_id": "<action_id>",
      "destination_id": "<action_id>",
      "condition": ""
    }}
  ]
}}

RULES:
- Gunakan app_name, app_id, app_version, large_image yang SAMA dengan source graph.
- Semua action id harus UUID baru (jangan reuse id dari source).
- "start" harus sama dengan id action PERTAMA dalam alur yang dibalik.
- branches menghubungkan action dalam URUTAN TERBALIK dari source.
- Hanya JSON murni — tidak ada teks tambahan di luar JSON.

{graph_section}
{rag_section}
{retry_section}"""


# ─────────────────────────────────────────────────────────────────────────────
# REVERSE PIPELINE — main entry point
# Dipanggil oleh POST /generate/reverse (generate.py)
# ─────────────────────────────────────────────────────────────────────────────

async def generate_reverse_from_graph(
    workflow_id:   str,
    workflow_name: str,
    retry_context: Optional[Any] = None,   # schemas.RetryContext | None
    db=None,
) -> str:
    """
    Generate reverse Shuffle workflow JSON menggunakan:
      1. Workflow graph dari Neo4j (disimpan Node.js di Step 4)
      2. RAG examples dari playbook vector store
      3. Ollama (local LLM) via llm.complete_json()

    Returns JSON string — Node.js akan parse dan validasi hasilnya.
    Error dilempar ke caller (endpoint /generate/reverse) untuk diteruskan ke Node.js.
    """
    attempt_num = retry_context.attempt if retry_context else 1
    logger.info(
        "[playbook_generator] generate_reverse_from_graph  id=%s  attempt=%d",
        workflow_id, attempt_num,
    )

    # 1. Ambil workflow graph dari Neo4j
    graph_records = await _get_workflow_graph(workflow_id)

    # 2. RAG retrieval
    rag_examples = []
    graph_context = []

    try:
        rag_results = await retrieval.hybrid_search(
            query=f"reverse response workflow {workflow_name}",
            top_k=3,
            db=db,
        )
        rag_examples = [r.get("content", "") for r in rag_results if r.get("content")]
    except Exception as rag_err:
        logger.warning("[RAG] failed: %s", rag_err)

    # 3. GRAPH CONTEXT (HARUS DI SINI)
    try:
        graph_context = await graph_retrieval.get_action_context(workflow_id)
    except Exception as graph_err:
        logger.warning("[GRAPH] failed: %s", graph_err)

    # 4. BUILD GRAPH REASONING
    graph_reasoning = ""

    if graph_context:
        graph_reasoning = "\nGRAPH CONTEXT (dependency + role awareness):\n" + "\n".join([
            f"- {g.get('label')} | role={g.get('role')} | app={g.get('app')} | next={g.get('next_actions')}"
            for g in graph_context
        ])

    # 5. PROMPT BUILD
    system_prompt = _build_reverse_system_prompt(
        graph_records,
        rag_examples,
        retry_context,
        graph_context
    )