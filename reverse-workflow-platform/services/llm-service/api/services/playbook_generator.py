"""Reverse pipeline: NL description -> LLM intermediate JSON -> Shuffle JSON.

If generation is not possible (no valid workflow after retries / no usable apps)
or any error occurs, the caller is expected to invoke the Action Recommender.
This module signals that by returning success=False with an error reason.
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional

from neo4j import AsyncGraphDatabase

from ..config import get_settings
settings = get_settings()
from .llm import llm                          # Ollama client
from .shuffle_translator import shuffle_translator
from .app_registry import app_registry
from . import retrieval                       # Hybrid search (BGE-M3 + reranker)
from .recommendation import recommender        # search + rerank, sama yang dipakai forward pipeline
from .graph_retrieval import graph_retrieval
from .reverse_context_builder import build

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# FORWARD PIPELINE — system prompt
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM = (
    "You design SOAR workflows. Convert the analyst's description into an "
    "intermediate workflow JSON. Respond ONLY with JSON of the form: "
    '{"name": str, "start": "n1", "nodes": [{"id": "n1", "APP": "virustotal", '
    '"ACTION": "lookup_url", "parameters": {"url": "${url}"}}], '
    '"edges": [{"from": "n1", "to": "n2", "conditions": []}]}. '
    "Use only APP keys from the provided registry list."
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
                 if not app_registry.resolve(n.get("APP")).get("_synthetic")]
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
      (:ACTION {action_id, label, app_name, action_name, app_id, app_version,
                role, position, is_start, parameters})
      -[:NEXT {condition}]->(:ACTION)

    PENTING: app_name / app_id / app_version dibaca dari properti ACTION langsung
    (bukan dari (:APP) via USES_APP) — field-field itu selalu ada di ACTION node.
    large_image dibaca dari APP node karena graphBuilder tidak menyimpannya di ACTION.
    """
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=settings.neo4j_auth,
    )
    query = """
        MATCH (w:WORKFLOW {workflow_id: $workflow_id})-[:CONTAINS]->(a:ACTION)

        OPTIONAL MATCH (a)-[r:NEXT]->(b:ACTION)
        OPTIONAL MATCH (a)-[:USES_APP]->(app:APP)

        WITH a, r, b, app
        RETURN
            a.action_id  AS id,
            a.label      AS name,
            a.action_name AS action_name,
            a.app_name   AS app_name,
            a.app_id     AS app_id,
            a.app_version AS app_version,
            COALESCE(app.large_image, '') AS large_image,
            a.is_start   AS is_start,
            a.position   AS position,
            collect({
                rel_type:    type(r),
                target_id:   b.action_id,
                target_name: b.label,
                condition:   r.condition
            }) AS transitions
    """
    async with driver.session() as session:
        result = await session.run(query, workflow_id=workflow_id)
        records = [record.data() async for record in result]

    await driver.close()

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
    """Bangun system prompt untuk Ollama: schema lengkap + concrete action table + retry errors."""

    # ── Concrete action data table ─────────────────────────────────────────
    # LLM harus COPY nilai ini persis, bukan mengarang.
    # Urutan tabel = urutan TERBALIK dari source (untuk reverse workflow).
    reversed_records = list(reversed(graph_records))

    action_rows = []
    for i, a in enumerate(reversed_records):
        transitions_str = ", ".join(
            f"{t.get('target_name')} (cond: {t.get('condition') or 'always'})"
            for t in a.get("transitions", [])
        ) or "(terminal)"

        action_rows.append(
            f"  ACTION[{i+1}]\n"
            f"    app_name    = {a.get('app_name') or '(unknown)'}\n"
            f"    app_id      = {a.get('app_id') or '(unknown)'}\n"
            f"    app_version = {a.get('app_version') or '(unknown)'}\n"
            f"    action_name = {a.get('action_name') or a.get('name') or ''}\n"
            f"    label       = {a.get('name') or ''}\n"
            f"    is_start    = {'true' if i == 0 else 'false'}\n"
            f"    source_flow → {transitions_str}"
            # large_image intentionally excluded — it is a large base64 blob
            # that would inflate the prompt. Python injects the correct value
            # from graph_records after generation (see _inject_large_images).
        )

    action_table = (
        "SOURCE ACTIONS (SUDAH DIURUTKAN TERBALIK — ACTION[1] adalah start node reverse):\n"
        + "\n".join(action_rows)
    )

    # ── RAG examples ──────────────────────────────────────────────────────
    rag_section = (
        "SIMILAR PLAYBOOK EXAMPLES (referensi format saja):\n"
        + "\n---\n".join(rag_examples[:1])
        if rag_examples
        else ""
    )

    # ── Retry errors ───────────────────────────────────────────────────────
    retry_section = ""
    if retry_context and not retry_context.valid:
        error_lines = "\n".join(
            f"  • [{e.code}] at {e.location}: {e.message}"
            + (f"\n    expected: {e.expected}" if hasattr(e, 'expected') and e.expected else "")
            + (f"\n    received: {e.received}" if hasattr(e, 'received') and e.received else "")
            for e in retry_context.errors
        )
        retry_section = (
            f"\n\nPREVIOUS ATTEMPT FAILED (attempt {retry_context.attempt}).\n"
            f"Fix ALL errors below before answering:\n{error_lines}\n"
            + (f"\nHINT: {retry_context.correction_instructions}"
               if retry_context.correction_instructions else "")
        )

    return f"""RESPOND WITH A JSON OBJECT ONLY. NO TEXT BEFORE OR AFTER. NO MARKDOWN. NO CODE FENCES.

You are a SOAR Workflow Engineer. Generate a REVERSE workflow JSON for Shuffle SOAR.

CRITICAL RULES — violations cause import failure:
1. YOUR ENTIRE RESPONSE MUST BE A SINGLE JSON OBJECT. Start your response with {{ and end with }}.
   Do NOT write "Here is...", do NOT use ``` fences, do NOT add any explanation.
2. Every "id" in actions and branches MUST be a valid UUID v4 — format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
   where x = hex digit [0-9a-f], the 3rd segment starts with 4, the 4th starts with 8/9/a/b.
   VALID:   "a3f1c2d4-1234-4abc-8def-000000000001"
   INVALID: "a1b2c3d4-e5f6-g7h8-i9j0-k0l1m2n3o4"  ← g/h/i/j/k letters are NOT valid hex
3. app_name, app_id, app_version — COPY EXACTLY from the ACTION TABLE below.
   Do NOT invent, modify, or leave these empty.
4. large_image — always output exactly: "large_image": "" (empty string). It will be filled server-side.
5. "name" field in each action — COPY the action_name value from the ACTION TABLE below.
6. Exactly ONE action must have "is_start_node": true — this must be ACTION[1] in the table.
7. All other actions must have "is_start_node": false.
8. "execution_delay" must be 0 (integer) for every action.
9. "branches" id fields must also be valid UUID v4 (not "branch1", "branch2", etc).
10. NEVER create a branch where source_id or destination_id is empty or missing.
    Terminal actions (last in the reversed flow) must NOT have any outgoing branch.
    Only create a branch when you have BOTH a valid source action id AND a valid destination action id.

OUTPUT SCHEMA (follow exactly):
{{
  "name": "<string — name of this reverse workflow>",
  "description": "<string — what this reverse workflow does>",
  "start": "<UUID — must equal the id you assigned to ACTION[1]>",
  "actions": [
    {{
      "id": "<new UUID v4>",
      "name": "<action_name from table>",
      "app_name": "<app_name from table — copy exactly>",
      "app_id": "<app_id from table — copy exactly>",
      "app_version": "<app_version from table — copy exactly>",
      "large_image": "",
      "label": "<label from table>",
      "is_start_node": <true for ACTION[1] only, false for all others>,
      "execution_delay": 0,
      "parameters": [{{"name": "<string>", "value": "<string>"}}],
      "position": {{"x": <number>, "y": <number>}}
    }}
  ],
  "branches": [
    {{
      "id": "<new UUID v4>",
      "source_id": "<action id>",
      "destination_id": "<action id>",
      "condition": ""
    }}
  ]
}}

{action_table}

{rag_section}
{retry_section}
REMINDER: output ONLY the JSON object. Do not write anything before {{ or after }}."""


def _sanitize_workflow(json_str: str) -> str:
    """
    Bersihkan output LLM sebelum dikembalikan ke Node.js:
    - Hapus branches dengan source_id atau destination_id kosong/null
      (LLM kadang membuat "terminal branch" untuk action terakhir yang
       seharusnya tidak punya outgoing branch sama sekali)
    """
    try:
        workflow = json.loads(json_str)
        original_count = len(workflow.get("branches", []))
        workflow["branches"] = [
            b for b in workflow.get("branches", [])
            if b.get("source_id") and b.get("destination_id")
        ]
        removed = original_count - len(workflow["branches"])
        if removed:
            logger.info("[sanitize] removed %d branch(es) with empty source_id/destination_id", removed)
        return json.dumps(workflow)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("[sanitize] parse failed, returning as-is: %s", exc)
        return json_str


def _extract_json(raw: str) -> str:
    """
    Strip preamble text and markdown fences dari LLM output.
    LLM kadang menulis "Here is the JSON:\n```\n{...}\n```" walau sudah diperintah tidak.

    Priority:
    1. Direct parse (sudah bersih)
    2. Ekstrak dari markdown code fence  ```...```
    3. Potong dari karakter '{' pertama sampai '}' terakhir
    """
    if not raw:
        return raw

    # 1. Already clean
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    # 2. Extract from ```json ... ``` or ``` ... ```
    import re
    fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", raw, re.IGNORECASE)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # 3. Find first '{' ... last '}' (handles "Here is the JSON:\n{...}")
    start = raw.find("{")
    end   = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = raw[start : end + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    return raw  # kembalikan raw — parse error akan dihandle Node.js


def _inject_large_images(raw_json_str: str, graph_records: List[Dict[str, Any]]) -> str:
    """
    Setelah Ollama generate JSON, inject large_image yang benar untuk setiap action
    berdasarkan app_id, menggunakan data dari graph_records (sudah ada di memori).

    Juga membersihkan preamble/markdown fence dari output LLM.
    Returns: clean JSON string dengan large_image ter-inject.
    """
    # Build lookup: app_id -> large_image dari source graph
    app_image_map: Dict[str, str] = {}
    for rec in graph_records:
        app_id     = rec.get("app_id")
        large_image = rec.get("large_image") or ""
        if app_id and large_image:
            app_image_map[app_id] = large_image

    # Strip preamble/fences dulu sebelum parse
    clean_str = _extract_json(raw_json_str)

    try:
        workflow = json.loads(clean_str)
        for action in workflow.get("actions", []):
            app_id = action.get("app_id")
            if app_id and app_id in app_image_map:
                action["large_image"] = app_image_map[app_id]
        return json.dumps(workflow)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("[inject_large_images] parse failed after extraction, returning extracted: %s", exc)
        return clean_str  # setidaknya kembalikan versi yang sudah strip preamble


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
    t_start = time.monotonic()

    # 1. Ambil workflow graph dari Neo4j
    logger.info("[STEP 1] Neo4j query start")
    graph_records = await _get_workflow_graph(workflow_id)
    logger.info("[STEP 1] Neo4j done  elapsed=%.1fs  nodes=%d",
                time.monotonic() - t_start, len(graph_records))
    if not graph_records:
        logger.warning("Empty graph result for workflow_id=%s", workflow_id)
        return []

    # 2. Build compressed context
    logger.info("[STEP 2] Build context start")
    context = build(graph_records)
    compressed_graph = context["graph"]
    app_catalog = context["app_catalog"]
    logger.info("[STEP 2] Context done  elapsed=%.1fs  graph=%d  apps=%d",
                time.monotonic() - t_start,
                len(compressed_graph), len(app_catalog.get("apps", [])))

    # 3. Graph context (Neo4j — role/dependency awareness)
    logger.info("[STEP 3] Graph context query start")
    graph_context: List[Dict[str, Any]] = []
    try:
        graph_context = await graph_retrieval.get_action_context(workflow_id)
        logger.info("[STEP 3] Graph context done  elapsed=%.1fs  records=%d",
                    time.monotonic() - t_start, len(graph_context))
    except Exception as graph_err:
        logger.warning("[STEP 3] Graph context failed  elapsed=%.1fs  err=%s",
                       time.monotonic() - t_start, graph_err)

    graph_reasoning = ""
    if graph_context:
        graph_reasoning = "\nGRAPH CONTEXT (dependency + role awareness):\n" + "\n".join([
            f"- {g.get('label')} | role={g.get('role')} | app={g.get('app')} | next={g.get('next_actions')}"
            for g in graph_context
        ])

    # 4. RAG — semantic search only, no reranker (reranker adds ~model-load cost per call on CPU)
    logger.info("[STEP 4] RAG search start")
    rag_examples: List[str] = []
    rag_query = " ".join(
        f"{node.get('app_name') or ''} {node.get('name') or ''}".strip()
        for node in compressed_graph
    ).strip()

    if rag_query:
        try:
            # Use retrieval.search() directly — skip recommender.recommend() which
            # also loads + runs the cross-encoder reranker (heavy, not needed here).
            rag_hits = await retrieval.search(rag_query, top_k=2)
            rag_examples = [
                f"{h['payload'].get('name', '')}: {h['payload'].get('description', '')}"
                for h in rag_hits
                if h.get("payload")
            ]
            logger.info("[STEP 4] RAG done  elapsed=%.1fs  hits=%d",
                        time.monotonic() - t_start, len(rag_examples))
        except Exception as rag_err:
            logger.warning("[STEP 4] RAG failed  elapsed=%.1fs  err=%s",
                           time.monotonic() - t_start, rag_err)
            rag_examples = []   # degraded gracefully — RAG is optional, not blocking

    # 5. Build prompts
    logger.info("[STEP 5] Build prompt start")
    system_prompt = _build_reverse_system_prompt(
        compressed_graph,
        rag_examples[:1],
        retry_context,
        graph_context
    )
    prompt = (
        f"Workflow Name: {workflow_name}\n\n"
        f"APP CATALOG (lightweight):\n{json.dumps(app_catalog, indent=2)}"
        + (f"\n\n{graph_reasoning}" if graph_reasoning else "")
    )
    logger.info("[STEP 5] Prompt ready  elapsed=%.1fs  system_len=%d  prompt_len=%d",
                time.monotonic() - t_start, len(system_prompt), len(prompt))

    # 6. Call Ollama
    logger.info("[STEP 6] Ollama call start  elapsed=%.1fs", time.monotonic() - t_start)
    try:
        raw_output = await llm.complete(prompt=prompt, system=system_prompt)
        logger.info("[STEP 6] Ollama done  elapsed=%.1fs  response_len=%d",
                    time.monotonic() - t_start,
                    len(raw_output) if raw_output else 0)
        if not raw_output:
            raise ValueError("Ollama returned empty response")

        # Post-process: inject large_image + strip invalid branches
        raw_output = _inject_large_images(raw_output, graph_records)
        raw_output = _sanitize_workflow(raw_output)
        logger.info("[STEP 6] post-processing done, returning to route handler")

        return raw_output
    except Exception as exc:
        logger.exception("[STEP 6] Ollama generation failed  elapsed=%.1fs",
                         time.monotonic() - t_start)
        raise RuntimeError(f"Reverse generation failed: {repr(exc)}")