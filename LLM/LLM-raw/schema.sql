-- =============================================================================
-- Shuffle AI Playbook Recommender v1.1 - schema
-- Adds: knowledge_base (RAG sources), hybrid search (tsvector), incident_history
-- PostgreSQL 16 + pgvector
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- -----------------------------------------------------------------------------
-- Playbook embedding (now with full-text search column for hybrid retrieval)
-- -----------------------------------------------------------------------------
CREATE TABLE playbook_embedding (
    workflow_id     TEXT PRIMARY KEY,
    name            TEXT        NOT NULL,
    description     TEXT,
    trigger_type    TEXT,
    mitre_tags      TEXT[]      NOT NULL DEFAULT '{}',
    apps_used       TEXT[]      NOT NULL DEFAULT '{}',
    alert_category  TEXT,
    embedding       vector(768) NOT NULL,
    -- Full-text search vector for keyword/BM25-style matching (hybrid search)
    search_doc      tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(description, '')), 'B') ||
        setweight(to_tsvector('english',
            coalesce(array_to_string(mitre_tags, ' '), '')), 'A') ||
        setweight(to_tsvector('english',
            coalesce(array_to_string(apps_used, ' '), '')), 'C') ||
        setweight(to_tsvector('english', coalesce(alert_category, '')), 'B')
    ) STORED,
    success_count   INT         NOT NULL DEFAULT 0,
    reject_count    INT         NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_playbook_vec ON playbook_embedding
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_playbook_fts ON playbook_embedding USING gin (search_doc);

-- -----------------------------------------------------------------------------
-- Knowledge base: runbooks, SOPs, policies, MITRE notes, anything else.
-- Same hybrid (vector + tsvector) pattern. doc_type lets you filter by source.
-- -----------------------------------------------------------------------------
CREATE TABLE knowledge_base (
    doc_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    doc_type        TEXT        NOT NULL,    -- runbook | sop | policy | mitre | other
    title           TEXT        NOT NULL,
    source_uri      TEXT,                     -- where this lives (Confluence URL, etc.)
    chunk_index     INT         NOT NULL DEFAULT 0,
    content         TEXT        NOT NULL,
    tags            TEXT[]      NOT NULL DEFAULT '{}',
    mitre_tags      TEXT[]      NOT NULL DEFAULT '{}',
    embedding       vector(768) NOT NULL,
    search_doc      tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(content, '')), 'B') ||
        setweight(to_tsvector('english',
            coalesce(array_to_string(tags, ' '), '')), 'C') ||
        setweight(to_tsvector('english',
            coalesce(array_to_string(mitre_tags, ' '), '')), 'A')
    ) STORED,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_kb_vec  ON knowledge_base USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_kb_fts  ON knowledge_base USING gin (search_doc);
CREATE INDEX idx_kb_type ON knowledge_base (doc_type);

-- -----------------------------------------------------------------------------
-- Incident history: closed cases with their outcome. Lets the model say
-- "alerts like this were false positives the last 3 times" instead of guessing.
-- -----------------------------------------------------------------------------
CREATE TABLE incident_history (
    incident_id     TEXT PRIMARY KEY,
    title           TEXT        NOT NULL,
    summary         TEXT,
    iocs            TEXT[]      NOT NULL DEFAULT '{}',
    mitre_tags      TEXT[]      NOT NULL DEFAULT '{}',
    workflow_used   TEXT,         -- which playbook ran (FK-ish, not enforced)
    outcome         TEXT,         -- true_positive | false_positive | benign | escalated
    embedding       vector(768) NOT NULL,
    closed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_inc_vec ON incident_history
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- -----------------------------------------------------------------------------
-- Recommendation feedback (unchanged from v1.0)
-- -----------------------------------------------------------------------------
CREATE TABLE recommendation_feedback (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    alert_id        TEXT        NOT NULL,
    workflow_id     TEXT        NOT NULL REFERENCES playbook_embedding (workflow_id),
    rank            INT         NOT NULL,
    decision        TEXT        NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_feedback_workflow ON recommendation_feedback (workflow_id);

CREATE OR REPLACE FUNCTION apply_feedback() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.decision = 'accepted' THEN
        UPDATE playbook_embedding SET success_count = success_count + 1,
               updated_at = now() WHERE workflow_id = NEW.workflow_id;
    ELSE
        UPDATE playbook_embedding SET reject_count = reject_count + 1,
               updated_at = now() WHERE workflow_id = NEW.workflow_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_apply_feedback
    AFTER INSERT ON recommendation_feedback
    FOR EACH ROW EXECUTE FUNCTION apply_feedback();
