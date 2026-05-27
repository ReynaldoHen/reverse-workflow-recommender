"""
Hybrid retrieval: combines vector search (semantic) with full-text search (keyword)
using Reciprocal Rank Fusion (RRF).

Why hybrid?
  - Vector search nails semantics but misses exact strings (CVE-2024-1234, filenames, IOCs).
  - FTS nails exact strings but misses paraphrase.
  - RRF merges both rankings with a single formula, no tuning needed.

RRF score = sum over each ranker of 1 / (k + rank_in_that_ranker).
k=60 is the literature default and works well across domains.
"""

import psycopg2.extras


RRF_K = 60


def _vector_search(cur, table, qvec, top_n, extra_cols=""):
    cols = "*" if not extra_cols else extra_cols
    cur.execute(
        f"""
        SELECT {cols},
               1 - (embedding <=> %s::vector) AS similarity
        FROM {table}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (qvec, qvec, top_n),
    )
    return cur.fetchall()


def _fts_search(cur, table, query_text, top_n, id_col, extra_cols=""):
    cols = "*" if not extra_cols else extra_cols
    # plainto_tsquery is forgiving of arbitrary alert text.
    cur.execute(
        f"""
        SELECT {cols},
               ts_rank(search_doc, plainto_tsquery('english', %s)) AS fts_rank
        FROM {table}
        WHERE search_doc @@ plainto_tsquery('english', %s)
        ORDER BY fts_rank DESC
        LIMIT %s
        """,
        (query_text, query_text, top_n),
    )
    return cur.fetchall()


def rrf_merge(rankings, id_key, k=RRF_K):
    """
    rankings: list of lists of rows, each list pre-sorted best-first.
    id_key: column name that uniquely identifies a row across rankings.
    Returns: list of (row, score) tuples, sorted best-first.
    """
    scores = {}
    rows_by_id = {}
    for ranking in rankings:
        for rank, row in enumerate(ranking, start=1):
            rid = row[id_key]
            scores[rid] = scores.get(rid, 0) + 1.0 / (k + rank)
            rows_by_id[rid] = row
    merged = sorted(
        ((rows_by_id[rid], score) for rid, score in scores.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    return merged


def hybrid_search_playbooks(conn, qvec, query_text, top_k):
    """Retrieve playbooks via hybrid search. Returns top_k row dicts."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        vec_hits = _vector_search(cur, "playbook_embedding", qvec, top_k * 2)
        fts_hits = _fts_search(cur, "playbook_embedding", query_text, top_k * 2,
                                id_col="workflow_id")
    merged = rrf_merge([vec_hits, fts_hits], id_key="workflow_id")
    return [row for row, _score in merged[:top_k]]


def hybrid_search_kb(conn, qvec, query_text, top_k, doc_types=None):
    """Retrieve knowledge base chunks via hybrid search."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if doc_types:
            cur.execute(
                """
                SELECT *, 1 - (embedding <=> %s::vector) AS similarity
                FROM knowledge_base
                WHERE doc_type = ANY(%s)
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (qvec, doc_types, qvec, top_k * 2),
            )
            vec_hits = cur.fetchall()
            cur.execute(
                """
                SELECT *,
                       ts_rank(search_doc, plainto_tsquery('english', %s)) AS fts_rank
                FROM knowledge_base
                WHERE doc_type = ANY(%s)
                  AND search_doc @@ plainto_tsquery('english', %s)
                ORDER BY fts_rank DESC
                LIMIT %s
                """,
                (query_text, doc_types, query_text, top_k * 2),
            )
            fts_hits = cur.fetchall()
        else:
            vec_hits = _vector_search(cur, "knowledge_base", qvec, top_k * 2)
            fts_hits = _fts_search(cur, "knowledge_base", query_text, top_k * 2,
                                    id_col="doc_id")
    merged = rrf_merge([vec_hits, fts_hits], id_key="doc_id")
    return [row for row, _score in merged[:top_k]]


def similar_incidents(conn, qvec, top_k):
    """Pure vector search over incident history (no FTS needed - we want semantic similarity)."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        return _vector_search(cur, "incident_history", qvec, top_k)
