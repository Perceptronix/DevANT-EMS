-- Phase 2: Initial Schema with pgvector support
-- This migration creates all required tables for the DevANT system

-- Enable pgvector extension
create extension if not exists vector;

-- ============================================================================
-- Projects Table
-- ============================================================================
create table if not exists projects (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    github_repo text,
    created_at timestamp with time zone default now(),
    updated_at timestamp with time zone default now()
);

create index if not exists idx_projects_name on projects(name);

-- ============================================================================
-- Raw Events Table
-- ============================================================================
create table if not exists raw_events (
    id uuid primary key default gen_random_uuid(),
    project_id uuid references projects(id) on delete cascade,
    source_type text not null, -- 'sentry', 'datadog', 'azure', 'sample', etc.
    service text,
    environment text default 'production',
    message text,
    stack_trace text,
    fingerprint text, -- Unique fingerprint for grouping
    metadata jsonb default '{}'::jsonb,
    occurred_at timestamp with time zone not null,
    created_at timestamp with time zone default now()
);

create index if not exists idx_raw_events_project_id on raw_events(project_id);
create index if not exists idx_raw_events_fingerprint on raw_events(fingerprint);
create index if not exists idx_raw_events_occurred_at on raw_events(occurred_at desc);
create index if not exists idx_raw_events_created_at on raw_events(created_at desc);

-- ============================================================================
-- Error Clusters Table
-- ============================================================================
create table if not exists error_clusters (
    id uuid primary key default gen_random_uuid(),
    project_id uuid references projects(id) on delete cascade,
    title text not null, -- Cluster signature/title
    representative_event_id uuid references raw_events(id),
    event_count integer default 0,
    severity text, -- 'S1', 'S2', 'S3', 'S4'
    status text default 'NEW', -- 'NEW', 'REGRESSION', 'ONGOING'
    confidence numeric default 0.0,
    created_at timestamp with time zone default now(),
    updated_at timestamp with time zone default now()
);

create index if not exists idx_error_clusters_project_id on error_clusters(project_id);
create index if not exists idx_error_clusters_status on error_clusters(status);
create index if not exists idx_error_clusters_severity on error_clusters(severity);

-- ============================================================================
-- Cluster Embeddings Table (pgvector)
-- ============================================================================
create table if not exists cluster_embeddings (
    cluster_id uuid primary key references error_clusters(id) on delete cascade,
    embedding vector(384),
    created_at timestamp with time zone default now()
);

-- Create IVFFlat index for fast similarity search
create index if not exists idx_cluster_embeddings_hnsw on cluster_embeddings 
using hnsw (embedding vector_cosine_ops);

-- ============================================================================
-- Incidents Table
-- ============================================================================
create table if not exists incidents (
    id uuid primary key default gen_random_uuid(),
    cluster_id uuid references error_clusters(id) on delete cascade,
    title text,
    summary text,
    root_cause text,
    recommendations jsonb default '{}'::jsonb,
    ai_confidence numeric default 0.0,
    created_at timestamp with time zone default now(),
    updated_at timestamp with time zone default now()
);

create index if not exists idx_incidents_cluster_id on incidents(cluster_id);
create index if not exists idx_incidents_created_at on incidents(created_at desc);

-- ============================================================================
-- Alerts Table
-- ============================================================================
create table if not exists alerts (
    id uuid primary key default gen_random_uuid(),
    incident_id uuid references incidents(id) on delete cascade,
    channel text, -- 'slack', 'email', 'linear', etc.
    status text default 'pending', -- 'pending', 'sent', 'failed'
    payload jsonb default '{}'::jsonb,
    sent_at timestamp with time zone,
    created_at timestamp with time zone default now()
);

create index if not exists idx_alerts_incident_id on alerts(incident_id);
create index if not exists idx_alerts_channel on alerts(channel);
create index if not exists idx_alerts_status on alerts(status);

-- ============================================================================
-- GitHub Events Table
-- ============================================================================
create table if not exists github_events (
    id uuid primary key default gen_random_uuid(),
    project_id uuid references projects(id) on delete cascade,
    event_type text, -- 'push', 'pull_request', 'issue', etc.
    payload jsonb default '{}'::jsonb,
    created_at timestamp with time zone default now()
);

create index if not exists idx_github_events_project_id on github_events(project_id);
create index if not exists idx_github_events_type on github_events(event_type);

-- ============================================================================
-- Deployments Table
-- ============================================================================
create table if not exists deployments (
    id uuid primary key default gen_random_uuid(),
    project_id uuid references projects(id) on delete cascade,
    provider text, -- 'vercel', 'github-actions', 'terraform', etc.
    deployment_id text, -- External deployment ID
    status text, -- 'success', 'failed', 'in_progress', 'rolled_back'
    metadata jsonb default '{}'::jsonb,
    deployed_at timestamp with time zone,
    created_at timestamp with time zone default now()
);

create index if not exists idx_deployments_project_id on deployments(project_id);
create index if not exists idx_deployments_deployed_at on deployments(deployed_at desc);
create index if not exists idx_deployments_status on deployments(status);

-- ============================================================================
-- Tickets Table (Linear/Jira/GitHub Issues)
-- ============================================================================
create table if not exists tickets (
    id uuid primary key default gen_random_uuid(),
    incident_id uuid references incidents(id) on delete cascade,
    provider text, -- 'linear', 'jira', 'github', etc.
    external_id text not null, -- ID from external system
    url text,
    status text, -- 'open', 'in_progress', 'closed', etc.
    created_at timestamp with time zone default now(),
    updated_at timestamp with time zone default now()
);

create index if not exists idx_tickets_incident_id on tickets(incident_id);
create index if not exists idx_tickets_provider on tickets(provider);
create index if not exists idx_tickets_external_id on tickets(provider, external_id);

-- ============================================================================
-- Mutes Table (for suppression rules)
-- ============================================================================
create table if not exists mutes (
    id uuid primary key default gen_random_uuid(),
    cluster_id uuid references error_clusters(id) on delete cascade,
    reason text,
    muted_by text,
    muted_until timestamp with time zone,
    created_at timestamp with time zone default now()
);

create index if not exists idx_mutes_cluster_id on mutes(cluster_id);
create index if not exists idx_mutes_until on mutes(muted_until);

-- ============================================================================
-- Signal Fusion Metadata (for operational context)
-- ============================================================================
create table if not exists signal_fusion_metadata (
    id uuid primary key default gen_random_uuid(),
    cluster_id uuid references error_clusters(id) on delete cascade,
    deployment_correlation numeric default 0.0,
    temporal_proximity numeric default 0.0,
    service_overlap_score numeric default 0.0,
    propagation_path text,
    metadata jsonb default '{}'::jsonb,
    created_at timestamp with time zone default now()
);

create index if not exists idx_signal_fusion_cluster on signal_fusion_metadata(cluster_id);

-- ============================================================================
-- Signature State (compatibility for previous JSON state)
-- ============================================================================
create table if not exists signature_states (
    signature text primary key,
    data jsonb default '{}'::jsonb,
    updated_at timestamp with time zone default now()
);

create index if not exists idx_signature_states_updated_at on signature_states(updated_at desc);
