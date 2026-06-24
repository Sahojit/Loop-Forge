CREATE_TABLES_SQL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'free',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'running',
    final_score FLOAT,
    iterations INT DEFAULT 0,
    tokens_used INT DEFAULT 0,
    tools_used TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    task_id UUID,
    action TEXT NOT NULL,
    metadata JSONB,
    ip_hash TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id);
"""

LOOP_STUDIO_TABLES_SQL = """
-- Skills: reusable Jinja2 prompt templates
CREATE TABLE IF NOT EXISTS skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    prompt_template TEXT NOT NULL,
    tool_tags TEXT[],
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Loops: user-defined recurring loops with cron schedule
CREATE TABLE IF NOT EXISTS loops (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_id UUID REFERENCES skills(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    description TEXT,
    cron_expression TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    max_iterations INT NOT NULL DEFAULT 3,
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Hooks: lifecycle event handlers per user
CREATE TABLE IF NOT EXISTS hooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    loop_id UUID REFERENCES loops(id) ON DELETE CASCADE,
    event TEXT NOT NULL,
    action TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Loop runs: every loop execution logged with idempotency
CREATE TABLE IF NOT EXISTS loop_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    loop_id UUID NOT NULL REFERENCES loops(id) ON DELETE CASCADE,
    idempotency_key TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    final_score FLOAT,
    iterations INT DEFAULT 0,
    tokens_used INT DEFAULT 0,
    tools_used TEXT[],
    final_output TEXT,
    score_history FLOAT[],
    triggered_by TEXT NOT NULL DEFAULT 'schedule',
    hooks_fired TEXT[],
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Notification configs: encrypted JSONB per user
CREATE TABLE IF NOT EXISTS notification_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    encrypted_config BYTEA NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Notification log: delivery attempts per loop run
CREATE TABLE IF NOT EXISTS notification_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    loop_run_id UUID REFERENCES loop_runs(id) ON DELETE SET NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INT NOT NULL DEFAULT 0,
    last_error TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_skills_user_id ON skills(user_id);
CREATE INDEX IF NOT EXISTS idx_loops_user_id ON loops(user_id);
CREATE INDEX IF NOT EXISTS idx_hooks_user_id ON hooks(user_id);
CREATE INDEX IF NOT EXISTS idx_hooks_loop_id ON hooks(loop_id);
CREATE INDEX IF NOT EXISTS idx_loop_runs_user_id ON loop_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_loop_runs_loop_id ON loop_runs(loop_id);
CREATE INDEX IF NOT EXISTS idx_loop_runs_idempotency ON loop_runs(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_notification_configs_user_id ON notification_configs(user_id);
CREATE INDEX IF NOT EXISTS idx_notification_log_user_id ON notification_log(user_id);
CREATE INDEX IF NOT EXISTS idx_notification_log_loop_run_id ON notification_log(loop_run_id);

-- Row Level Security
ALTER TABLE skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE loops ENABLE ROW LEVEL SECURITY;
ALTER TABLE hooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE loop_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS skills_user_policy ON skills;
CREATE POLICY skills_user_policy ON skills
    USING (user_id = current_setting('app.current_user_id', TRUE)::uuid);

DROP POLICY IF EXISTS loops_user_policy ON loops;
CREATE POLICY loops_user_policy ON loops
    USING (user_id = current_setting('app.current_user_id', TRUE)::uuid);

DROP POLICY IF EXISTS hooks_user_policy ON hooks;
CREATE POLICY hooks_user_policy ON hooks
    USING (user_id = current_setting('app.current_user_id', TRUE)::uuid);

DROP POLICY IF EXISTS loop_runs_user_policy ON loop_runs;
CREATE POLICY loop_runs_user_policy ON loop_runs
    USING (user_id = current_setting('app.current_user_id', TRUE)::uuid);

DROP POLICY IF EXISTS notification_configs_user_policy ON notification_configs;
CREATE POLICY notification_configs_user_policy ON notification_configs
    USING (user_id = current_setting('app.current_user_id', TRUE)::uuid);

DROP POLICY IF EXISTS notification_log_user_policy ON notification_log;
CREATE POLICY notification_log_user_policy ON notification_log
    USING (user_id = current_setting('app.current_user_id', TRUE)::uuid);
"""
