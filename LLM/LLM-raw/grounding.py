"""
Anti-hallucination guardrails for the rerank step.

Three layers, applied in order:
  1. Schema validation       - Pydantic rejects malformed JSON
  2. Citation validation     - each ranked item must cite a real evidence_id
  3. Confidence threshold    - drop items below MIN_CONFIDENCE

If everything is dropped, the caller falls back to vector-similarity order.
"""

import json
import os
from pydantic import BaseModel, Field, ValidationError, field_validator


MIN_CONFIDENCE = int(os.environ.get("MIN_CONFIDENCE", "6"))


class RankedItem(BaseModel):
    candidate_index: int = Field(ge=1)
    confidence: int = Field(ge=1, le=10)
    evidence_id: str          # MUST quote an actual evidence_id we provided
    reason: str = Field(min_length=10, max_length=400)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_filler(cls, v: str) -> str:
        # Cheap heuristic - reject obvious filler.
        filler = {"n/a", "none", "unknown", "see above", "matches"}
        if v.strip().lower() in filler:
            raise ValueError("reason is filler")
        return v


class RerankResponse(BaseModel):
    ranked: list[RankedItem]


def parse_strict(raw_text: str, valid_evidence_ids: set[str],
                  num_candidates: int) -> list[RankedItem]:
    """
    Parse and validate the LLM response. Returns only items that:
      - parse against the schema
      - cite an evidence_id we actually provided (no fabrication)
      - clear MIN_CONFIDENCE
      - point at a real candidate_index (1..num_candidates)
    Returns [] on any parse failure - caller falls back.
    """
    text = raw_text.strip()
    # Strip code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    # Locate outermost JSON object
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
        parsed = RerankResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return []

    kept = []
    for item in parsed.ranked:
        if item.candidate_index > num_candidates:
            continue                                    # invented an index
        if item.evidence_id not in valid_evidence_ids:
            continue                                    # invented a citation
        if item.confidence < MIN_CONFIDENCE:
            continue                                    # under threshold
        kept.append(item)
    return kept


def build_grounded_prompt(query: str, candidates: list[dict],
                          knowledge_chunks: list[dict],
                          incident_history: list[dict]) -> tuple[str, set[str]]:
    """
    Build the rerank prompt with explicit evidence_ids the model must cite.
    Returns (prompt, set_of_valid_evidence_ids).
    """
    valid_ids: set[str] = set()
    sections = []

    # Candidates block - each gets a stable evidence id
    cand_lines = []
    for i, c in enumerate(candidates, start=1):
        ev = f"PB-{i}"
        valid_ids.add(ev)
        cand_lines.append(
            f"[{ev}] Candidate {i}: {c['name']} - {c.get('description', '')} "
            f"(MITRE: {', '.join(c.get('mitre_tags', []))}; "
            f"history: {c.get('success_count', 0)} accepted / "
            f"{c.get('reject_count', 0)} rejected)"
        )
    sections.append("CANDIDATES:\n" + "\n".join(cand_lines))

    # Knowledge base context
    if knowledge_chunks:
        kb_lines = []
        for i, k in enumerate(knowledge_chunks, start=1):
            ev = f"KB-{i}"
            valid_ids.add(ev)
            snippet = (k.get("content") or "")[:400].replace("\n", " ")
            kb_lines.append(f"[{ev}] {k.get('doc_type', 'doc')}: "
                            f"{k.get('title', '')} - {snippet}")
        sections.append("KNOWLEDGE BASE:\n" + "\n".join(kb_lines))

    # Past incidents
    if incident_history:
        inc_lines = []
        for i, h in enumerate(incident_history, start=1):
            ev = f"INC-{i}"
            valid_ids.add(ev)
            inc_lines.append(
                f"[{ev}] {h.get('title', '')} - outcome: {h.get('outcome', '')}; "
                f"playbook used: {h.get('workflow_used', '')}"
            )
        sections.append("PAST INCIDENTS:\n" + "\n".join(inc_lines))

    rules = (
        "You are a SOC triage assistant. Rank the candidates for this alert.\n"
        "STRICT RULES - violations cause your output to be discarded:\n"
        f"1. Reply with ONLY this JSON, nothing else: "
        f'{{"ranked":[{{"candidate_index":<1..{len(candidates)}>,'
        f'"confidence":<1..10>,"evidence_id":"<one of the bracketed IDs above>",'
        f'"reason":"<one sentence citing the evidence>"}}]}}\n'
        "2. evidence_id MUST be a bracketed ID exactly as shown "
        "(e.g. PB-2, KB-1, INC-3). Do not invent IDs.\n"
        "3. If no evidence supports a candidate, OMIT it entirely. "
        "Do not include candidates you cannot ground in the provided evidence.\n"
        f"4. confidence below {MIN_CONFIDENCE} will be discarded. "
        "Be honest - it is fine to return an empty list if nothing fits.\n"
        "5. Order best-first."
    )

    prompt = f"{rules}\n\nALERT: {query}\n\n" + "\n\n".join(sections)
    return prompt, valid_ids
