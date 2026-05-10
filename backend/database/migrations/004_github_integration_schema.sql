-- Migration: 004_github_integration_schema.sql
-- Purpose: create GitHub integration tables for commit, PR, deployment, and workflow ingestion

-- Projects metadata for GitHub repositories
create table if not exists github_repositories (
    id uuid primary key default gen_random_uuid(),
    project_id uuid references projects(id) on delete cascade,
    owner text not null,
    name text not null,
    full_name text not null unique,
    url text,
    default_branch text,
    description text,
    extra_metadata jsonb default '{}'::jsonb,
    synced_at timestamp with time zone,
    created_at timestamp with time zone default now(),
    updated_at timestamp with time zone default now()
);

create index if not exists idx_github_repositories_project_id on github_repositories(project_id);
create index if not exists idx_github_repositories_full_name on github_repositories(full_name);

create table if not exists github_commits (
    id uuid primary key default gen_random_uuid(),
    repository_id uuid references github_repositories(id) on delete cascade,
    sha text not null,
    author text,
    message text,
    files_changed integer,
    additions integer,
    deletions integer,
    url text,
    committed_at timestamp with time zone,
    changed_files jsonb default '[]'::jsonb,
    extra_metadata jsonb default '{}'::jsonb,
    created_at timestamp with time zone default now()
);

create index if not exists idx_github_commits_repository_id on github_commits(repository_id);
create index if not exists idx_github_commits_sha on github_commits(sha);
create index if not exists idx_github_commits_committed_at on github_commits(committed_at);

create table if not exists github_pull_requests (
    id uuid primary key default gen_random_uuid(),
    repository_id uuid references github_repositories(id) on delete cascade,
    number integer not null,
    title text,
    author text,
    state text,
    merged boolean default false,
    merged_at timestamp with time zone,
    created_at_gh timestamp with time zone,
    updated_at_gh timestamp with time zone,
    closed_at timestamp with time zone,
    url text,
    files_changed integer,
    additions integer,
    deletions integer,
    extra_metadata jsonb default '{}'::jsonb,
    created_at timestamp with time zone default now()
);

create index if not exists idx_github_pull_requests_repository_id on github_pull_requests(repository_id);
create index if not exists idx_github_pull_requests_number on github_pull_requests(number);
create index if not exists idx_github_pull_requests_merged_at on github_pull_requests(merged_at);
create index if not exists idx_github_pull_requests_state on github_pull_requests(state);

create table if not exists github_deployments (
    id uuid primary key default gen_random_uuid(),
    repository_id uuid references github_repositories(id) on delete cascade,
    deployment_id text not null,
    ref text,
    sha text,
    environment text,
    status text,
    url text,
    creator text,
    deployed_at timestamp with time zone,
    extra_metadata jsonb default '{}'::jsonb,
    created_at timestamp with time zone default now()
);

create index if not exists idx_github_deployments_repository_id on github_deployments(repository_id);
create index if not exists idx_github_deployments_deployment_id on github_deployments(deployment_id);
create index if not exists idx_github_deployments_environment on github_deployments(environment);
create index if not exists idx_github_deployments_deployed_at on github_deployments(deployed_at);

create table if not exists github_workflows (
    id uuid primary key default gen_random_uuid(),
    repository_id uuid references github_repositories(id) on delete cascade,
    workflow_id text not null,
    name text,
    status text,
    conclusion text,
    ref text,
    sha text,
    actor text,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    url text,
    extra_metadata jsonb default '{}'::jsonb,
    created_at timestamp with time zone default now()
);

create index if not exists idx_github_workflows_repository_id on github_workflows(repository_id);
create index if not exists idx_github_workflows_workflow_id on github_workflows(workflow_id);
create index if not exists idx_github_workflows_status on github_workflows(status);
create index if not exists idx_github_workflows_completed_at on github_workflows(completed_at);
