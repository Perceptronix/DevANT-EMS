-- Migration: 002_add_raw_events_embedding.sql
-- Purpose: add `embedding` vector column to `raw_events` for pgvector-based embeddings
-- Upgrade: add column and index
-- Downgrade: drop index and column

-- === UPGRADE ===
-- Ensure pgvector extension present
create extension if not exists vector;

-- Add embedding column (vector dimension 384)
alter table raw_events
    add column if not exists embedding vector(384);

-- Create HNSW index for fast similarity search on embeddings
do $$
begin
    if not exists (
        select 1 from pg_class c join pg_namespace n on c.relnamespace = n.oid
        where c.relname = 'idx_raw_events_embedding_hnsw'
    ) then
        execute 'create index idx_raw_events_embedding_hnsw on raw_events using hnsw (embedding vector_cosine_ops)';
    end if;
end
$$;

-- === DOWNGRADE ===
-- To rollback, drop index then drop column. Keep pgvector extension.
-- Note: Execute downgrade statements separately when performing rollback.

-- DROP INDEX IF EXISTS idx_raw_events_embedding_hnsw;
-- ALTER TABLE raw_events DROP COLUMN IF EXISTS embedding;
