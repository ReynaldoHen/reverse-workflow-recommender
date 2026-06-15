-- PostgreSQL schema (also auto-created by SQLAlchemy on startup).
CREATE TABLE IF NOT EXISTS playbooks (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(120) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    category VARCHAR(80) NOT NULL,
    description TEXT NOT NULL,
    steps JSONB NOT NULL,
    apps JSONB NOT NULL,
    shuffle_json JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_playbooks_category ON playbooks(category);

CREATE TABLE IF NOT EXISTS generated_workflows (
    id SERIAL PRIMARY KEY,
    description TEXT NOT NULL,
    intermediate_json JSONB NOT NULL,
    shuffle_json JSONB,
    status VARCHAR(40) DEFAULT 'generated',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    playbook_slug VARCHAR(120) NOT NULL,
    helpful INT NOT NULL,
    rank INT,
    created_at TIMESTAMP DEFAULT NOW()
);
