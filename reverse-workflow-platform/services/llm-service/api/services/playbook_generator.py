"""Reverse pipeline: query Neo4j graph (+ pemetaan HAS_REVERSE) -> bangun prompt
berbasis pemetaan reverse -> Ollama -> raw Shuffle workflow JSON.

Dipanggil oleh endpoint POST /generate/reverse. RAG/Qdrant sudah dihapus.
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional

from neo4j import AsyncGraphDatabase

from ..config import get_settings
settings = get_settings()
from .llm import llm                          # Ollama client
from .graph_retrieval import graph_retrieval

logger = logging.getLogger(__name__)

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
    rev_by_id: Dict[str, Dict[str, Any]],
    retry_context: Optional[Any],
) -> str:
    """Bangun system prompt reverse berbasis PEMETAAN (HAS_REVERSE), tanpa RAG.

    Untuk tiap source action (urutan dibalik), prompt memberi tahu LLM reverse
    action yang harus dikeluarkan sesuai status pemetaan:
      - auto_mapped            -> keluarkan action name = reverse_action_name
      - needs_llm              -> LLM menyimpulkan kebalikan; jika ragu, manual review
      - requires_manual_review -> placeholder requires_manual_review=true (jangan mengarang)
    """
    reversed_records = list(reversed(graph_records))

    # Lewati action ber-status no_reverse_needed (read-only/utilitas) — tidak masuk output.
    kept = []
    skipped = []
    for a in reversed_records:
        rev = rev_by_id.get(a.get("id"), {}) or {}
        if (rev.get("reverse_status") or "needs_llm") == "no_reverse_needed":
            skipped.append(a.get("action_name") or a.get("name") or a.get("id"))
        else:
            kept.append(a)

    rows = []
    for i, a in enumerate(kept):
        aid = a.get("id")
        rev = rev_by_id.get(aid, {}) or {}
        status = rev.get("reverse_status") or "needs_llm"
        reverse_name = rev.get("reverse_action_name") or ""

        if status == "auto_mapped" and reverse_name:
            instruction = (
                f"OUTPUT reverse action: name = '{reverse_name}' "
                f"(requires_manual_review=false). Salin app_name/app_id/app_version "
                f"dari source, pertahankan parameter yang relevan (mis. IP/user yang sama)."
            )
        elif status == "requires_manual_review":
            reason = rev.get("reverse_reason") or "tidak ada pasangan pembalik"
            instruction = (
                f"TIDAK ADA reverse yang aman ({reason}). OUTPUT placeholder: "
                f"name = 'manual_review_required', requires_manual_review=true. "
                f"JANGAN mengarang aksi pembalik."
            )
        else:  # needs_llm
            instruction = (
                "TIDAK ada di kamus. Simpulkan aksi kebalikan yang paling tepat dari app "
                "yang sama berdasarkan makna action sumber. Jika tidak yakin, set "
                "requires_manual_review=true (jangan mengarang)."
            )

        transitions_str = ", ".join(
            f"{t.get('target_name')} (cond: {t.get('condition') or 'always'})"
            for t in a.get("transitions", [])
        ) or "(terminal)"

        rows.append(
            f"  SOURCE_ACTION[{i+1}]\n"
            f"    source_name = {a.get('action_name') or a.get('name') or ''}\n"
            f"    app_name    = {a.get('app_name') or '(unknown)'}\n"
            f"    app_id      = {a.get('app_id') or '(unknown)'}\n"
            f"    app_version = {a.get('app_version') or '(unknown)'}\n"
            f"    is_start    = {'true' if i == 0 else 'false'}\n"
            f"    source_flow → {transitions_str}\n"
            f"    REVERSE     → {instruction}"
        )

    skip_note = ""
    if skipped:
        skip_note = (
            "\n\nACTION YANG DILEWATI (read-only/utilitas, JANGAN dimasukkan ke output): "
            + ", ".join(str(s) for s in skipped)
        )

    action_table = (
        "REVERSE MAPPING TABLE (urutan SUDAH dibalik — SOURCE_ACTION[1] = start node reverse;\n"
        "HANYA action di tabel ini yang boleh muncul di output):\n"
        + "\n".join(rows)
        + skip_note
    )

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

    return f"""RESPOND WITH A JSON OBJECT ONLY. NO TEXT BEFORE OR AFTER. NO MARKDOWN. NO CODE FENCES.

You are a SOAR Workflow Engineer. Generate a REVERSE (rollback) workflow JSON for Shuffle SOAR.
For each source action you MUST output its mapped REVERSE action (see table), NOT a copy of the
source action. The reverse workflow runs the inverse actions in reversed order.

CRITICAL RULES — violations cause import failure:
1. RESPONSE = SATU JSON OBJECT. Mulai dengan {{ dan akhiri dengan }}. Tanpa teks/markdown/code fence.
2. Setiap "id" di actions dan branches WAJIB UUID v4 (xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx).
3. app_name, app_id, app_version — SALIN PERSIS dari source action pada tabel.
4. large_image — selalu "" (akan diisi server-side).
5. "name" tiap action — gunakan reverse action sesuai kolom REVERSE pada tabel (BUKAN source_name),
   kecuali requires_manual_review=true → name = "manual_review_required".
6. Tambahkan field "requires_manual_review": true/false pada SETIAP action sesuai instruksi tabel.
7. Tepat SATU action punya "is_start_node": true → yaitu SOURCE_ACTION[1] di tabel.
8. "execution_delay" = 0 (integer) untuk semua action.
9. branches.id juga UUID v4; jangan buat branch dengan source_id/destination_id kosong.
10. Terminal action (terakhir pada alur terbalik) tidak boleh punya outgoing branch.
11. JANGAN membuat parameter baru di luar yang tersedia. JANGAN mengeksekusi rollback.

OUTPUT SCHEMA (ikuti persis):
{{
  "name": "<string — nama reverse workflow>",
  "description": "<string — apa yang dilakukan reverse workflow ini>",
  "start": "<UUID — sama dengan id action untuk SOURCE_ACTION[1]>",
  "actions": [
    {{
      "id": "<UUID v4 baru>",
      "name": "<reverse action_name dari tabel, atau 'manual_review_required'>",
      "app_name": "<app_name dari tabel — salin persis>",
      "app_id": "<app_id dari tabel — salin persis>",
      "app_version": "<app_version dari tabel — salin persis>",
      "large_image": "",
      "label": "<label singkat>",
      "is_start_node": <true hanya untuk SOURCE_ACTION[1], selain itu false>,
      "execution_delay": 0,
      "requires_manual_review": <true/false sesuai tabel>,
      "parameters": [{{"name": "<string>", "value": "<string>"}}],
      "position": {{"x": <number>, "y": <number>}}
    }}
  ],
  "branches": [
    {{
      "id": "<UUID v4 baru>",
      "source_id": "<action id>",
      "destination_id": "<action id>",
      "condition": ""
    }}
  ]
}}

{action_table}
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
      1. Workflow graph dari Neo4j (disimpan Node.js di Step 4), termasuk
         pemetaan HAS_REVERSE -> REVERSE_ACTION (auto_mapped / needs_llm /
         requires_manual_review).
      2. Ollama (local LLM) via llm.complete().

    Returns JSON string — Node.js akan parse, validasi, dan import.
    """
    attempt_num = retry_context.attempt if retry_context else 1
    logger.info(
        "[playbook_generator] generate_reverse_from_graph  id=%s  attempt=%d",
        workflow_id, attempt_num,
    )
    t_start = time.monotonic()

    # 1. Ambil workflow graph (Action nodes) dari Neo4j
    graph_records = await _get_workflow_graph(workflow_id)
    if not graph_records:
        logger.warning("Empty graph result for workflow_id=%s", workflow_id)
        return []

    # 2. Ambil graph context + pemetaan reverse (HAS_REVERSE) dari Neo4j
    rev_by_id: Dict[str, Dict[str, Any]] = {}
    graph_context: List[Dict[str, Any]] = []
    try:
        graph_context = await graph_retrieval.get_action_context(workflow_id)
        for g in graph_context:
            rev_by_id[g.get("id")] = {
                "reverse_action_name": g.get("reverse_action_name"),
                "reverse_status":      g.get("reverse_status"),
                "reverse_reason":      g.get("reverse_reason"),
            }
    except Exception as graph_err:
        logger.warning("[GRAPH] context/reverse-map query failed: %s", graph_err)

    # 3. Build system prompt berbasis pemetaan reverse (tanpa RAG)
    system_prompt = _build_reverse_system_prompt(
        graph_records,
        rev_by_id,
        retry_context,
    )

    # 4. User prompt ringkas
    prompt = (
        f"Workflow Name: {workflow_name}\n\n"
        "Hasilkan reverse workflow JSON sesuai REVERSE MAPPING TABLE pada system prompt."
    )
    logger.info("[STEP] Prompt ready  elapsed=%.1fs  system_len=%d",
                time.monotonic() - t_start, len(system_prompt))

    # 5. Call Ollama
    try:
        raw_output = await llm.complete(prompt=prompt, system=system_prompt)
        if not raw_output:
            raise ValueError("Ollama returned empty response")

        # Post-process: inject large_image + strip invalid branches
        raw_output = _inject_large_images(raw_output, graph_records)
        raw_output = _sanitize_workflow(raw_output)
        logger.info("[STEP] Ollama done  elapsed=%.1fs", time.monotonic() - t_start)
        return raw_output

    except Exception as exc:
        logger.exception("[REVERSE] Ollama generation failed  elapsed=%.1fs",
                         time.monotonic() - t_start)
        raise RuntimeError(f"Reverse generation failed: {repr(exc)}")

