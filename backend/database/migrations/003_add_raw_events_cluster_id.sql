-- Migration: 003_add_raw_events_cluster_id.sql
-- Purpose: allow assigning clustered event group id to each raw_event

alter table raw_events
    add column if not exists cluster_id uuid references error_clusters(id) on delete set null;

create index if not exists idx_raw_events_cluster_id
    on raw_events(cluster_id);
