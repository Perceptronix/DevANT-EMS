-- Migration: 006_incident_deployment_correlation.sql
-- Purpose: store incident-to-deployment correlation results

create table if not exists incident_deployment_correlations (
    id uuid primary key default gen_random_uuid(),
    incident_id uuid references incidents(id) on delete cascade,
    cluster_id uuid references error_clusters(id) on delete cascade,
    representative_event_id uuid references raw_events(id) on delete set null,
    suspect_deployments jsonb default '[]'::jsonb,
    likely_affected_services jsonb default '[]'::jsonb,
    confidence_score numeric default 0.0,
    temporal_proximity_score numeric default 0.0,
    service_match_score numeric default 0.0,
    provider_match_score numeric default 0.0,
    notes text,
    created_at timestamp with time zone default now()
);

create index if not exists idx_incident_deployment_correlations_incident_id
    on incident_deployment_correlations(incident_id);

create index if not exists idx_incident_deployment_correlations_cluster_id
    on incident_deployment_correlations(cluster_id);

create index if not exists idx_incident_deployment_correlations_confidence
    on incident_deployment_correlations(confidence_score desc);