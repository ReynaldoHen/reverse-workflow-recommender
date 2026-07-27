import json
import logging
import time
from typing import Any, Dict, List, Optional

from neo4j import AsyncGraphDatabase

from ..config import get_settings
settings = get_settings()
from .llm import llm
from .graph_retrieval import graph_retrieval

logger = logging.getLogger(__name__)

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
            a.parameters AS parameters,
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

    for rec in records:
        rec["transitions"] = [
            t for t in rec.get("transitions", [])
            if t.get("target_id") is not None
        ]

    return records


def _summarize_config(parameters_raw) -> str:
    """Ringkas konfigurasi (parameter) action agar LLM bisa menyimpulkan kebalikannya.
    parameters_raw bisa JSON string (dari Neo4j) atau list."""
    try:
        params = parameters_raw if isinstance(parameters_raw, list) else json.loads(parameters_raw or "[]")
    except Exception:
        params = []
    parts = []
    for p in params or []:
        if not isinstance(p, dict):
            continue
        name = p.get("name") or ""
        val = "" if p.get("value") is None else str(p.get("value"))
        val = " ".join(val.split())
        if len(val) > 140:
            val = val[:140] + "…"
        if name:
            parts.append(f"{name}={val}")
    return "; ".join(parts) if parts else "(tanpa parameter)"


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
      - requires_manual_review -> OMIT dari output (ditandai untuk review terpisah, jangan mengarang)
    """
    reversed_records = list(reversed(graph_records))

    kept = []
    skipped = []
    for a in reversed_records:
        rev = rev_by_id.get(a.get("id"), {}) or {}
        status = rev.get("reverse_status") or "needs_llm"
        if status in ("no_reverse_needed", "requires_manual_review"):
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
                f"(requires_manual_review=false). Salin app_name/app_id/app_version dari source, "
                f"dan bawa parameter relevan dari CONFIG di bawah (mis. id/IP/user yang sama) "
                f"agar reverse menunjuk objek yang benar."
            )
        else:
            instruction = (
                "Simpulkan kebalikan dari CONFIG di bawah. "
                "Jika action ini READ-ONLY (method GET, atau sekadar mengambil/get/list data) "
                "→ JANGAN keluarkan (OMIT). "
                "Jika MENGUBAH state: untuk custom_action keluarkan name='custom_action' dengan "
                "app/app_id/app_version SAMA, SALIN config lalu UBAH hanya bagian yang membalik "
                "operasi (contoh: body {\"accountEnabled\": false} → {\"accountEnabled\": true}; "
                "path .../disable → .../enable; method tetap). Untuk action bernama, keluarkan "
                "action yang membalik dengan parameter yang sesuai. Jangan mengarang endpoint."
            )

        cfg = _summarize_config(a.get("parameters"))

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
            f"    CONFIG      = {cfg}\n"
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

    return f"""OUTPUT: ONE JSON OBJECT ONLY. Start with {{ end with }}. No text, no markdown, no code fence, no explanation.

You generate a REVERSE (rollback) Shuffle SOAR workflow. For each source action emit its mapped REVERSE
action from the table below (NOT a copy of the source), in reversed order.

RULES (breaking these fails the import):
- "id" of every action & branch = UUID v4. Copy app_name/app_id/app_version EXACTLY from the table.
- "name" = the REVERSE action from the table. Actions marked OMIT must NOT appear in the output.
- large_image = "". execution_delay = 0. Exactly ONE action has is_start_node=true (SOURCE_ACTION[1]).
- Add "requires_manual_review": false on every emitted action. Do not invent parameters. Do not execute anything.
- No branch with empty source_id/destination_id. The terminal action has no outgoing branch.

SCHEMA:
{{"name":"<str>","description":"<str>","start":"<UUID of SOURCE_ACTION[1]>",
"actions":[{{"id":"<UUID>","name":"<reverse name>","app_name":"<copy>","app_id":"<copy>","app_version":"<copy>","large_image":"","label":"<short>","is_start_node":<bool>,"execution_delay":0,"requires_manual_review":false,"parameters":[{{"name":"<str>","value":"<str>"}}],"position":{{"x":<num>,"y":<num>}}}}],
"branches":[{{"id":"<UUID>","source_id":"<id>","destination_id":"<id>","condition":""}}]}}

{action_table}
{retry_section}
Output ONLY the JSON object now."""


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

    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    import re
    fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", raw, re.IGNORECASE)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    start = raw.find("{")
    end   = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = raw[start : end + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    return raw


def _inject_large_images(raw_json_str: str, graph_records: List[Dict[str, Any]]) -> str:
    """
    Setelah Ollama generate JSON, inject large_image yang benar untuk setiap action
    berdasarkan app_id, menggunakan data dari graph_records (sudah ada di memori).

    Juga membersihkan preamble/markdown fence dari output LLM.
    Returns: clean JSON string dengan large_image ter-inject.
    """
    app_image_map: Dict[str, str] = {}
    for rec in graph_records:
        app_id     = rec.get("app_id")
        large_image = rec.get("large_image") or ""
        if app_id and large_image:
            app_image_map[app_id] = large_image

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
        return clean_str


async def generate_reverse_from_graph(
    workflow_id:   str,
    workflow_name: str,
    retry_context: Optional[Any] = None,
    db=None,
) -> tuple:
    """
    Generate reverse Shuffle workflow JSON menggunakan:
      1. Workflow graph dari Neo4j (disimpan Node.js di Step 4), termasuk
         pemetaan HAS_REVERSE -> REVERSE_ACTION (auto_mapped / needs_llm /
         requires_manual_review).
      2. Ollama (local LLM) via llm.complete().

    Returns (raw_output, prompt) — Node.js akan parse, validasi, import; prompt
    untuk dokumentasi/paper.
    """
    attempt_num = retry_context.attempt if retry_context else 1
    logger.info(
        "[playbook_generator] generate_reverse_from_graph  id=%s  attempt=%d",
        workflow_id, attempt_num,
    )
    t_start = time.monotonic()

    graph_records = await _get_workflow_graph(workflow_id)
    if not graph_records:
        logger.warning("Empty graph result for workflow_id=%s", workflow_id)
        return [], None

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

    emittable = sum(
        1 for g in graph_context
        if (g.get("reverse_status") or "needs_llm") in ("auto_mapped", "needs_llm")
    )
    if graph_context and emittable == 0:
        logger.info("[STEP] No emittable actions — skip LLM, return empty reverse  elapsed=%.1fs",
                    time.monotonic() - t_start)
        return json.dumps({
            "name": f"{workflow_name} (Reverse)",
            "description": "Tidak ada action yang dapat dibalik otomatis; semua ditandai untuk peninjauan manual.",
            "start": "",
            "actions": [],
            "branches": [],
        }), None

    system_prompt = _build_reverse_system_prompt(
        graph_records,
        rev_by_id,
        retry_context,
    )

    prompt = (
        f"Workflow Name: {workflow_name}\n\n"
        "Hasilkan reverse workflow JSON sesuai REVERSE MAPPING TABLE pada system prompt."
    )
    logger.info("[STEP] Prompt ready  elapsed=%.1fs  system_len=%d",
                time.monotonic() - t_start, len(system_prompt))

    prompt_combined = (
        "=== SYSTEM PROMPT ===\n" + system_prompt +
        "\n\n=== USER PROMPT ===\n" + prompt
    )

    try:
        raw_output = await llm.complete(prompt=prompt, system=system_prompt)
        if not raw_output:
            raise ValueError("Ollama returned empty response")

        raw_output = _inject_large_images(raw_output, graph_records)
        raw_output = _sanitize_workflow(raw_output)
        logger.info("[STEP] Ollama done  elapsed=%.1fs", time.monotonic() - t_start)
        return raw_output, prompt_combined

    except Exception as exc:
        logger.exception("[REVERSE] Ollama generation failed  elapsed=%.1fs",
                         time.monotonic() - t_start)
        raise RuntimeError(f"Reverse generation failed: {repr(exc)}")

