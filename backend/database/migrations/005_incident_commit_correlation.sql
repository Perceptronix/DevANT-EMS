-- Migration: 005_incident_commit_correlation.sql
-- Purpose: store incident-to-commit correlation results

create table if not exists incident_commit_correlations (
    id uuid primary key default gen_random_uuid(),
    incident_id uuid references incidents(id) on delete cascade,
    cluster_id uuid references error_clusters(id) on delete cascade,
    representative_event_id uuid references raw_events(id) on delete set null,
    repository_id uuid references github_repositories(id) on delete set null,
    suspect_commits jsonb default '[]'::jsonb,
    likely_changed_files jsonb default '[]'::jsonb,
    confidence_score numeric default 0.0,
    service_match_score numeric default 0.0,
    deployment_timing_score numeric default 0.0,
    file_match_score numeric default 0.0,
    notes text,
    created_at timestamp with time zone default now()
);

create index if not exists idx_incident_commit_correlations_incident_id
    on incident_commit_correlations(incident_id);

create index if not exists idx_incident_commit_correlations_cluster_id
    on incident_commit_correlations(cluster_id);

create index if not exists idx_incident_commit_correlations_repository_id
    on incident_commit_correlations(repository_id);

create index if not exists idx_incident_commit_correlations_confidence
    on incident_commit_correlations(confidence_score desc);
