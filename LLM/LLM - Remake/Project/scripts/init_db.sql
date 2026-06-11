-- AI Playbook Recommender — PostgreSQL schema init

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── Playbooks ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS playbooks (
    id                        VARCHAR(36)   PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name                      VARCHAR(500)  NOT NULL,
    description               TEXT,
    use_cases                 TEXT[]        DEFAULT '{}',
    integrations              TEXT[]        DEFAULT '{}',
    triggers                  TEXT[]        DEFAULT '{}',
    tags                      TEXT[]        DEFAULT '{}',
    category                  VARCHAR(100),
    shuffle_workflow_id       VARCHAR(100),
    shuffle_json              JSONB         DEFAULT '{}',
    confidence_threshold      FLOAT         DEFAULT 0.75,
    qdrant_point_id           VARCHAR(36),
    created_at                TIMESTAMP     DEFAULT NOW(),
    updated_at                TIMESTAMP     DEFAULT NOW(),
    last_synced_from_shuffle  TIMESTAMP,
    is_active                 BOOLEAN       DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_playbooks_category    ON playbooks (category);
CREATE INDEX IF NOT EXISTS idx_playbooks_integrations ON playbooks USING GIN (integrations);
CREATE INDEX IF NOT EXISTS idx_playbooks_tags         ON playbooks USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_playbooks_fts ON playbooks
    USING GIN (to_tsvector('english',
        coalesce(name,'') || ' ' || coalesce(description,'') || ' ' ||
        coalesce(array_to_string(tags,' '),'') || ' ' ||
        coalesce(array_to_string(integrations,' '),'')
    ));

-- ── Feedback ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feedback (
    id                       SERIAL        PRIMARY KEY,
    query                    TEXT          NOT NULL,
    session_id               VARCHAR(100),
    recommended_playbook_id  VARCHAR(36),
    confidence_score         FLOAT,
    accepted                 BOOLEAN,
    analyst_id               VARCHAR(100),
    intent                   VARCHAR(50),
    use_refinement           BOOLEAN       DEFAULT FALSE,
    created_at               TIMESTAMP     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_playbook ON feedback (recommended_playbook_id);
CREATE INDEX IF NOT EXISTS idx_feedback_accepted ON feedback (accepted);

-- ── Sessions ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id                   VARCHAR(100)  PRIMARY KEY,
    analyst_id           VARCHAR(100),
    conversation_history JSONB         DEFAULT '[]',
    created_at           TIMESTAMP     DEFAULT NOW(),
    updated_at           TIMESTAMP     DEFAULT NOW()
);

-- ── Users ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id               VARCHAR(36)   PRIMARY KEY DEFAULT gen_random_uuid()::text,
    username         VARCHAR(100)  UNIQUE NOT NULL,
    hashed_password  VARCHAR(255)  NOT NULL,
    api_key          VARCHAR(64)   UNIQUE,
    is_active        BOOLEAN       DEFAULT TRUE,
    role             VARCHAR(20)   DEFAULT 'analyst',
    created_at       TIMESTAMP     DEFAULT NOW()
);
