---
inclusion: always
---

# DevANT GitHub REST API — Steering Reference

Source of truth: `github/rest-api-description` (OpenAPI 3.0.3, v1.1.4)
Spec: `descriptions/api.github.com/api.github.com.json`
Integration root: `src/integrations/github/`

Total spec operations: 1,153 | Paths: 765 | Schemas: 926 | Paginated endpoints: 199

---

## How to Use This Integration

Always import from the barrel:

```ts
import { createGitHubIntegration } from 'src/integrations/github';

const gh = createGitHubIntegration({ token: process.env.GITHUB_TOKEN! });
```

This gives you: `gh.repos`, `gh.pulls`, `gh.issues`, `gh.actions`,
`gh.security`, `gh.webhooks`, `gh.orchestrator`, `gh.client`, `gh.cache`.

---

## Authentication Rules

| Token type | Rate limit | Use for |
|---|---|---|
| GitHub App installation token | 15,000 req/hr | Production — always prefer |
| Personal Access Token (PAT) | 5,000 req/hr | Local dev only |
| Unauthenticated | 60 req/hr | Never |

Required headers on every request (handled by `GitHubClient`):
```
Authorization: Bearer {token}
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
User-Agent: DevANT/1.0
```

GitHub App JWT signing lives in `client/github-app-auth.ts`.
Installation tokens expire after 1 hour — `GitHubAppAuth.getToken()` auto-rotates at 55 min.

Traffic endpoints (`/traffic/views`, `/traffic/clones`) require push access
and are **not available via GitHub Apps** — use PAT for those only.

---

## Service Layer — All APIs and Their Uses

### `gh.repos` — `GitHubReposService`

File: `src/integrations/github/services/repos-service.ts`

| Method | operationId | GitHub endpoint | DevANT use |
|---|---|---|---|
| `getRepository(owner, repo)` | `repos/get` | `GET /repos/{owner}/{repo}` | Repo metadata baseline, health scoring, language detection |
| `listCommits(owner, repo, opts)` | `repos/list-commits` | `GET /repos/{owner}/{repo}/commits` | Commit velocity, author attribution, incremental sync via `since`/`until` |
| `getCommit(owner, repo, ref)` | `repos/get-commit` | `GET /repos/{owner}/{repo}/commits/{ref}` | Diff detail, additions/deletions, files changed — churn and risk scoring |
| `compareCommits(owner, repo, base, head)` | `repos/compare-commits` | `GET /repos/{owner}/{repo}/compare/{basehead}` | Lead time: compare deploy SHA to feature branch base |
| `listBranches(owner, repo, opts)` | `repos/list-branches` | `GET /repos/{owner}/{repo}/branches` | Branch inventory, stale branch detection |
| `listContributors(owner, repo)` | `repos/list-contributors` | `GET /repos/{owner}/{repo}/contributors` | Contributor ranking, bus factor baseline |
| `listLanguages(owner, repo)` | `repos/list-languages` | `GET /repos/{owner}/{repo}/languages` | Tech stack detection, language bytes map |
| `listTags(owner, repo)` | `repos/list-tags` | `GET /repos/{owner}/{repo}/tags` | Tag inventory for release correlation |
| `getContributorsStats(owner, repo)` | `repos/get-contributors-stats` | `GET /repos/{owner}/{repo}/stats/contributors` | Weekly commits per contributor — bus factor, ownership, churn |
| `getCommitActivityStats(owner, repo)` | `repos/get-commit-activity-stats` | `GET /repos/{owner}/{repo}/stats/commit_activity` | 52-week commit frequency — deployment frequency proxy |
| `getCodeFrequencyStats(owner, repo)` | `repos/get-code-frequency-stats` | `GET /repos/{owner}/{repo}/stats/code_frequency` | Weekly additions/deletions — churn detection, refactor risk |
| `getParticipationStats(owner, repo)` | `repos/get-participation-stats` | `GET /repos/{owner}/{repo}/stats/participation` | Owner vs all-contributor split — team health |
| `getTrafficViews(owner, repo, per)` | `repos/get-views` | `GET /repos/{owner}/{repo}/traffic/views` | Repo view count — stakeholder reporting (PAT only) |
| `getTrafficClones(owner, repo, per)` | `repos/get-clones` | `GET /repos/{owner}/{repo}/traffic/clones` | Clone count — adoption tracking (PAT only) |
| `listDeployments(owner, repo, opts)` | `repos/list-deployments` | `GET /repos/{owner}/{repo}/deployments` | Deployment frequency (DORA), environment inventory |
| `listDeploymentStatuses(owner, repo, deploymentId)` | `repos/list-deployment-statuses` | `GET /repos/{owner}/{repo}/deployments/{deployment_id}/statuses` | MTTR, change failure rate (DORA) |
| `listReleases(owner, repo)` | `repos/list-releases` | `GET /repos/{owner}/{repo}/releases` | Release cadence, version history |
| `getLatestRelease(owner, repo)` | `repos/get-latest-release` | `GET /repos/{owner}/{repo}/releases/latest` | Current production version for wallboard |

Stats endpoints (`getContributorsStats`, `getCommitActivityStats`, `getCodeFrequencyStats`,
`getParticipationStats`) return `202 Accepted` while GitHub computes them.
`GitHubRetryHandler` retries automatically every 5s, up to 6 attempts.
Cache these results for 1 hour — they are expensive.

`listCommits` options: `sha`, `path`, `author`, `committer`, `since: Date`, `until: Date`, `perPage`.
`listDeployments` options: `sha`, `ref`, `task`, `environment`.

---

### `gh.pulls` — `GitHubPullsService`

File: `src/integrations/github/services/pulls-service.ts`

| Method | operationId | GitHub endpoint | DevANT use |
|---|---|---|---|
| `listPullRequests(owner, repo, opts)` | `pulls/list` | `GET /repos/{owner}/{repo}/pulls` | PR inventory, open/closed state, stale PR detection |
| `getPullRequest(owner, repo, pullNumber)` | `pulls/get` | `GET /repos/{owner}/{repo}/pulls/{pull_number}` | PR detail: cycle time, additions/deletions, merge status |
| `listReviews(owner, repo, pullNumber)` | `pulls/list-reviews` | `GET /repos/{owner}/{repo}/pulls/{pull_number}/reviews` | Review latency, approval patterns, review coverage |
| `listCommits(owner, repo, pullNumber)` | `pulls/list-commits` | `GET /repos/{owner}/{repo}/pulls/{pull_number}/commits` | Commits per PR — complexity proxy, lead time |
| `listFiles(owner, repo, pullNumber)` | `pulls/list-files` | `GET /repos/{owner}/{repo}/pulls/{pull_number}/files` | Files changed — hotspot detection, risk scoring |
| `listRequestedReviewers(owner, repo, pullNumber)` | `pulls/list-requested-reviewers` | `GET /repos/{owner}/{repo}/pulls/{pull_number}/requested_reviewers` | Reviewer assignment, bottleneck detection |
| `listPullRequestsForCommit(owner, repo, commitSha)` | `repos/list-pull-requests-associated-with-commit` | `GET /repos/{owner}/{repo}/commits/{commit_sha}/pulls` | Link commit → PR for DORA lead time calculation |

`listPullRequests` options: `state` (`open`/`closed`/`all`), `head`, `base`,
`sort` (`created`/`updated`/`popularity`/`long-running`), `direction`.

`getPullRequest` returns the full `pull-request` schema (48 properties) including
`additions`, `deletions`, `changed_files`, `commits` — the list endpoint returns
`pull-request-simple` (36 properties) which omits those diff stats.
Always call `getPullRequest` when you need diff size for cycle time or risk scoring.

---

### `gh.issues` — `GitHubIssuesService`

File: `src/integrations/github/services/issues-service.ts`

| Method | operationId | GitHub endpoint | DevANT use |
|---|---|---|---|
| `listIssues(owner, repo, opts)` | `issues/list-for-repo` | `GET /repos/{owner}/{repo}/issues` | Issue inventory, open/closed rate, sprint backlog |
| `listPureIssues(owner, repo, opts)` | `issues/list-for-repo` (filtered) | `GET /repos/{owner}/{repo}/issues` | Issues only — filters out PRs that GitHub returns in this endpoint |
| `getIssue(owner, repo, issueNumber)` | `issues/get` | `GET /repos/{owner}/{repo}/issues/{issue_number}` | Issue detail: labels, milestone, assignee, time-to-close |
| `listMilestones(owner, repo, opts)` | `issues/list-milestones` | `GET /repos/{owner}/{repo}/milestones` | Sprint/milestone tracking, due date forecasting |
| `getMilestone(owner, repo, milestoneNumber)` | `issues/get-milestone` | `GET /repos/{owner}/{repo}/milestones/{milestone_number}` | Single milestone detail for sprint analysis |
| `listLabels(owner, repo)` | `issues/list-labels-for-repo` | `GET /repos/{owner}/{repo}/labels` | Label taxonomy for issue classification |

**Critical**: `GET /repos/{owner}/{repo}/issues` returns both issues AND pull requests.
Always use `listPureIssues` when you want only real issues.
Filter condition: absence of `pull_request` field on the response object.

`listIssues` options: `milestone`, `state`, `assignee`, `creator`, `mentioned`,
`labels` (comma-separated string), `sort`, `direction`, `since: Date`.

`listMilestones` options: `state` (`open`/`closed`/`all`),
`sort` (`due_on`/`completeness`), `direction`.

---

### `gh.actions` — `GitHubActionsService`

File: `src/integrations/github/services/actions-service.ts`

| Method | operationId | GitHub endpoint | DevANT use |
|---|---|---|---|
| `listWorkflowRunsForRepo(owner, repo, opts)` | `actions/list-workflow-runs-for-repo` | `GET /repos/{owner}/{repo}/actions/runs` | CI run history, deployment frequency, build success rate |
| `getWorkflowRun(owner, repo, runId)` | `actions/get-workflow-run` | `GET /repos/{owner}/{repo}/actions/runs/{run_id}` | Run detail: status, conclusion, timing — lead time, MTTR |
| `getWorkflowRunTiming(owner, repo, runId)` | `actions/get-workflow-run-usage` | `GET /repos/{owner}/{repo}/actions/runs/{run_id}/timing` | Build duration in ms — CI performance trending (PAT only) |
| `listJobsForWorkflowRun(owner, repo, runId, filter)` | `actions/list-jobs-for-workflow-run` | `GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs` | Job-level timing, step breakdown — CI bottleneck detection |
| `listWorkflows(owner, repo)` | `actions/list-repo-workflows` | `GET /repos/{owner}/{repo}/actions/workflows` | Workflow inventory for CI pipeline mapping |
| `listWorkflowRuns(owner, repo, workflowId, opts)` | `actions/list-workflow-runs` | `GET /repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs` | Per-workflow run history for deployment frequency per pipeline |

`WorkflowRunListOptions`: `actor`, `branch`, `event`, `status`, `created` (ISO 8601 range
`"2024-01-01..2024-12-31"`), `excludePullRequests`, `checkSuiteId`, `headSha`.

`status` enum: `completed` | `action_required` | `cancelled` | `failure` | `neutral` |
`skipped` | `stale` | `success` | `timed_out` | `in_progress` | `queued` | `requested` |
`waiting` | `pending`.

Response for `listWorkflowRunsForRepo` and `listWorkflowRuns` is wrapped:
`{ total_count, workflow_runs: [] }` — the service unwraps and returns the array directly.

`getWorkflowRunTiming` has `x-github.enabledForGitHubApps = false` — requires OAuth token, not installation token.

---

### `gh.security` — `GitHubSecurityService`

File: `src/integrations/github/services/security-service.ts`

| Method | operationId | GitHub endpoint | DevANT use |
|---|---|---|---|
| `listCodeScanningAlerts(owner, repo, opts)` | `code-scanning/list-alerts-for-repo` | `GET /repos/{owner}/{repo}/code-scanning/alerts` | Open vulnerability count, severity distribution for risk scoring |
| `listSecretScanningAlerts(owner, repo, opts)` | `secret-scanning/list-alerts-for-repo` | `GET /repos/{owner}/{repo}/secret-scanning/alerts` | Secret leak detection, exposure window calculation |
| `listDependabotAlerts(owner, repo, opts)` | `dependabot/list-alerts-for-repo` | `GET /repos/{owner}/{repo}/dependabot/alerts` | Dependency vulnerability tracking, CVSS scoring |
| `getSecurityRiskSnapshot(owner, repo)` | (aggregator) | All three above in parallel | Single risk snapshot: severity buckets, overall risk level |

`listCodeScanningAlerts` options: `toolName`, `ref`, `state` (`open`/`closed`/`dismissed`/`fixed`),
`severity` (`critical`/`high`/`medium`/`low`/`warning`/`note`/`error`).

`listSecretScanningAlerts` options: `state` (`open`/`resolved`), `secretType` (comma-separated),
`resolution`, `sort`, `direction`.

`listDependabotAlerts` options: `state` (`auto_dismissed`/`dismissed`/`fixed`/`open`),
`severity`, `ecosystem`, `scope` (`development`/`runtime`), `sort`, `direction`.

`getSecurityRiskSnapshot` runs all three in `Promise.allSettled` — partial failures
don't crash the snapshot. Risk level logic:
- `critical` → any critical SAST/Dependabot alert OR any open secret alert
- `high` → more than 5 high-severity alerts
- `medium` → any high-severity alert
- `low` → no high/critical alerts

---

### `gh.webhooks` — `GitHubWebhooksService`

File: `src/integrations/github/services/webhooks-service.ts`

| Method | operationId | GitHub endpoint | DevANT use |
|---|---|---|---|
| `listRepoWebhooks(owner, repo)` | `repos/list-webhooks` | `GET /repos/{owner}/{repo}/hooks` | Verify DevANT webhook registration, audit hook config |
| `createRepoWebhook(owner, repo, config)` | `repos/create-webhook` | `POST /repos/{owner}/{repo}/hooks` | Register DevANT webhook for real-time event ingestion |
| `getRepoWebhook(owner, repo, hookId)` | `repos/get-webhook` | `GET /repos/{owner}/{repo}/hooks/{hook_id}` | Verify webhook active status and subscribed events |
| `updateRepoWebhook(owner, repo, hookId, updates)` | `repos/update-webhook` | `PATCH /repos/{owner}/{repo}/hooks/{hook_id}` | Secret rotation, event subscription changes |
| `deleteRepoWebhook(owner, repo, hookId)` | `repos/delete-webhook` | `DELETE /repos/{owner}/{repo}/hooks/{hook_id}` | Deregister on repo offboarding |
| `listWebhookDeliveries(owner, repo, hookId)` | `repos/list-webhook-deliveries` | `GET /repos/{owner}/{repo}/hooks/{hook_id}/deliveries` | Delivery audit, failure detection, replay identification |
| `redeliverWebhookDelivery(owner, repo, hookId, deliveryId)` | `repos/redeliver-webhook-delivery` | `POST /repos/{owner}/{repo}/hooks/{hook_id}/deliveries/{delivery_id}/attempts` | Manual replay for missed events during downtime |
| `listOrgWebhooks(org)` | `orgs/list-webhooks` | `GET /orgs/{org}/hooks` | Org-level webhook inventory |
| `createOrgWebhook(org, config)` | `orgs/create-webhook` | `POST /orgs/{org}/hooks` | Org-level hook — covers all repos, preferred for multi-repo |
| `ensureRepoWebhook(owner, repo, url, secret)` | (idempotent helper) | list + create/update | Idempotent registration — checks before creating, repairs if broken |

`DEVANT_WEBHOOK_EVENTS` constant lists all 18 events DevANT subscribes to:
`push`, `pull_request`, `pull_request_review`, `pull_request_review_comment`,
`issues`, `issue_comment`, `deployment`, `deployment_status`, `release`,
`workflow_run`, `check_run`, `check_suite`, `create`, `delete`,
`code_scanning_alert`, `secret_scanning_alert`, `repository`, `member`.

Prefer `createOrgWebhook` for multi-repo installations — one hook covers all repos.
Use `ensureRepoWebhook` for single-repo onboarding — it is idempotent and safe to call repeatedly.

---

## Webhook Ingestion Layer

### `GitHubWebhookHandler`

File: `src/integrations/github/webhooks/webhook-handler.ts`

Verifies and parses incoming webhook HTTP requests.

```ts
const handler = new GitHubWebhookHandler({ secret, deliveryStore });
const result = await handler.process(rawBody, headers);
// result is null → reject with 401 (invalid signature)
// result.duplicate === true → already processed, return 200 and skip
```

Signature verification uses HMAC-SHA256 with timing-safe comparison.
Delivery deduplication uses `X-GitHub-Delivery` header stored with 24h TTL.
Inject your own `DeliveryStore` (Redis recommended):
```ts
interface DeliveryStore {
  has(deliveryId: string): Promise<boolean>;
  add(deliveryId: string, ttlSeconds?: number): Promise<void>;
}
```

### `GitHubWebhookRouter`

File: `src/integrations/github/webhooks/webhook-router.ts`

Routes verified payloads to DevANT intelligence pipelines.

```ts
const router = new GitHubWebhookRouter();
router
  .on<PushEventPayload>('push', async (payload, deliveryId) => { /* commit ingestion */ })
  .on<DeploymentStatusEventPayload>('deployment_status', async (payload) => { /* DORA */ })
  .on<WorkflowRunEventPayload>('workflow_run', async (payload) => { /* CI intelligence */ });

await router.dispatch(result.event, result.payload, result.deliveryId);
```

All handlers run concurrently via `Promise.allSettled` — one failing handler
does not block others.

Typed payload interfaces available for: `PushEventPayload`, `PullRequestEventPayload`,
`DeploymentEventPayload`, `DeploymentStatusEventPayload`, `WorkflowRunEventPayload`,
`ReleaseEventPayload`, `IssuesEventPayload`.

---

## Pagination Rules

All list endpoints use RFC 5988 Link header pagination.
199 endpoints in the spec return a `Link` response header.

```
Link: <https://api.github.com/...?page=2>; rel="next",
      <https://api.github.com/...?page=5>; rel="last"
```

Spec-confirmed params (`components/parameters`):
- `per_page`: integer, default 30 — always pass 100 for efficiency
- `page`: integer, default 1

All service methods call `fetchAllPages` internally — you get the full array back,
pagination is handled transparently.

### Incremental sync

Use `since: Date` to fetch only new items — never full re-fetch:

```ts
// Only commits since last sync
await gh.repos.listCommits(owner, repo, { since: lastSyncAt });

// Only issues updated since last sync
await gh.issues.listIssues(owner, repo, { since: lastSyncAt, state: 'all' });
```

Endpoints supporting `since`: `repos/list-commits`, `issues/list-for-repo`.

### Cursor pagination

Two endpoints use cursor-based pagination (`components/parameters/cursor`):
`secret-scanning/list-alerts-for-repo` and one other.
`fetchAllPages` handles both Link header and cursor transparently.

---

## ETag Caching Rules

`GitHubClient` sends `If-None-Match` automatically when an ETag is stored.
A `304 Not Modified` response costs zero rate limit quota.

TTL presets in `CACHE_TTL`:

| Constant | Value | Used for |
|---|---|---|
| `CACHE_TTL.REPOSITORY` | 5 min | `repos/get` |
| `CACHE_TTL.COMMIT` | 10 min | `repos/get-commit` |
| `CACHE_TTL.PULL_REQUEST` | 2 min | `pulls/get` |
| `CACHE_TTL.ISSUE` | 2 min | `issues/get` |
| `CACHE_TTL.DEPLOYMENT` | 3 min | deployment detail |
| `CACHE_TTL.RELEASE` | 10 min | `repos/get-latest-release` |
| `CACHE_TTL.STATS` | 60 min | all stats endpoints |
| `CACHE_TTL.TRAFFIC` | 60 min | traffic endpoints |
| `CACHE_TTL.ACTIONS` | 1 min | `actions/get-workflow-run` |

Invalidate cache on webhook events:
```ts
// On push webhook → invalidate commits cache for that repo
cache.invalidatePattern(`repos/list-commits:owner=${owner}&repo=${repo}`);
```

---

## Rate Limit Rules

`GitHubRateLimitMonitor` tracks `X-RateLimit-Remaining` and `X-RateLimit-Reset`
from every response. Automatically pauses when remaining < 100.

`GitHubRetryHandler` handles:
- `429` → wait for `retry_after`, then retry
- `403` with `retry_after` in body → secondary rate limit, wait and retry
- `202` → stats computing, retry every 5s up to 6 times
- `500`/`502`/`503`/`504` → exponential backoff with jitter, up to 5 attempts
- Timeout (`AbortError`) → exponential backoff, up to 5 attempts

**20 operations** have `x-github.triggersNotification = true` — these trigger
GitHub's abuse detection. `GitHubRateLimitMonitor` enforces a 3s minimum delay
between calls to these operations. They include:
`POST /repos/{owner}/{repo}/issues`, `POST /repos/{owner}/{repo}/pulls`,
`POST /repos/{owner}/{repo}/releases`, `PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge`,
and others. Never call these in a tight loop.

Check quota proactively:
```ts
// operationId: rate-limit/get
// GET /rate_limit
// Response: rate-limit-overview schema
const { data } = await gh.client.request({ method: 'GET', path: '/rate_limit' });
console.log(data.resources.core.remaining); // out of 15000 (App) or 5000 (PAT)
```

---

## DORA Metrics — Data Sources and Transforms

File: `src/integrations/github/transforms/dora-transforms.ts`

| DORA metric | Primary webhook | REST fallback | Transform function |
|---|---|---|---|
| Deployment Frequency | `deployment` | `repos/list-deployments` | `calculateDeploymentFrequency(runs, periodDays)` |
| Lead Time for Changes | `push` + `workflow_run` | `repos/list-commits` + `actions/list-workflow-runs-for-repo` | `calculateLeadTimeFromRuns(runs)` |
| Change Failure Rate | `deployment_status` | `repos/list-deployment-statuses` | `calculateChangeFailureRate(deployments, statusesByDeploymentId)` |
| MTTR | `deployment_status` sequence | `repos/list-deployment-statuses` | `calculateMTTR(deployments, statusesByDeploymentId)` |

Build a full scorecard:
```ts
import { buildDORAScorecard } from 'src/integrations/github';

const scorecard = buildDORAScorecard(
  calculateDeploymentFrequency(workflowRuns, 30),
  calculateLeadTimeFromRuns(workflowRuns),
  calculateChangeFailureRate(deployments, statusMap),
  calculateMTTR(deployments, statusMap),
);
// scorecard.overallRating: 'elite' | 'high' | 'medium' | 'low'
```

Rating thresholds (DORA 2023 benchmarks):
- Deployment frequency: elite ≥ 1/day, high ≥ 1/week, medium ≥ 1/month
- Lead time: elite < 1hr, high < 24hr, medium < 1 week
- Change failure rate: elite ≤ 5%, high ≤ 10%, medium ≤ 15%
- MTTR: elite < 1hr, high < 24hr, medium < 1 week

---

## AI Intelligence Transforms

File: `src/integrations/github/transforms/ai-intelligence-transforms.ts`

| Function | Input | Output | Use |
|---|---|---|---|
| `scoreCommitRisk(commit)` | `GitHubCommit` | `CommitRiskSignal` (score 0–100) | Flag risky commits for review |
| `detectStalePR(pr, reviews, threshold)` | `GitHubPullRequest` + reviews | `StalePRSignal` | Stale PR detection, blocker identification |
| `calculateBusFactor(stats)` | `GitHubContributorStats[]` | `BusFactorResult` | Knowledge concentration risk |
| `detectHotspots(commits, topN)` | commits with files | `HotspotFile[]` | High-churn file detection |
| `analyzeSprintMilestone(milestone)` | `GitHubMilestone` | `SprintSignal` | Sprint velocity, forecast, on-track status |
| `analyzeReleaseCadence(releases)` | `GitHubRelease[]` | `ReleaseCadenceResult` | Release frequency rating |

Commit risk factors: `large_diff` (>1000 lines), `many_files` (>20 files),
`high_churn` (deletions > 2× additions), `poor_message` (message < 10 chars).

Stale PR staleness levels: `fresh` → `aging` (>7 days) → `stale` (>14 days) → `abandoned` (>30 days).

Bus factor: number of contributors whose removal would eliminate 50%+ of commits.
Critical = 1, High = 2, Medium = 3, Low = 4+.

---

## Mappers — GitHub Schema → DevANT Domain

File: `src/integrations/github/mappers/repo-mapper.ts`

Always map raw GitHub responses before storing or processing:

```ts
import { mapCommit, mapPullRequest, mapWorkflowRun } from 'src/integrations/github';

const commit = mapCommit(rawGitHubCommit);
// commit.cycleTimeHours, commit.isMergeCommit, commit.shortSha — computed fields
```

Derived fields added by mappers:

| Mapper | Derived fields |
|---|---|
| `mapCommit` | `shortSha`, `messageFirstLine`, `isMergeCommit` |
| `mapPullRequest` | `cycleTimeHours`, `mergeTimeHours` |
| `mapIssue` | `timeToCloseHours`, `isPullRequest` |
| `mapDeploymentStatus` | `isSuccess`, `isFailure` |
| `mapWorkflowRun` | `durationMs`, `isSuccess`, `isFailure` |
| `mapContributorStats` | `weeks[].weekStart` (Date from Unix timestamp) |

---

## Zod Validation

File: `src/integrations/github/validators/zod-schemas.ts`

Validate at the ingestion boundary — never trust raw API responses in pipelines:

```ts
import { CommitSchema, safeValidate } from 'src/integrations/github';

const result = safeValidate(CommitSchema, rawData, 'repos/get-commit');
if (result.success) {
  // result.data is typed and validated
} else {
  // result.error is ZodError — logged but ingestion continues
}
```

All schemas use `.passthrough()` — additive spec changes (new fields) never break validation.
`safeValidate` logs warnings but does not throw — ingestion is resilient to schema drift.

Available schemas: `RepositorySchema`, `CommitSchema`, `PullRequestSchema`,
`PullRequestSimpleSchema`, `PullRequestReviewSchema`, `IssueSchema`,
`DeploymentSchema`, `DeploymentStatusSchema`, `ReleaseSchema`,
`WorkflowRunSchema`, `RateLimitOverviewSchema`, `ContributorStatsSchema`.

---

## Ingestion Orchestrator

File: `src/integrations/github/ingestion/ingestion-orchestrator.ts`

Full repo ingestion in one call:

```ts
const result = await gh.orchestrator.ingest({
  owner: 'acme',
  repo: 'api',
  lastSyncAt: new Date('2024-01-01'), // incremental — only fetches since this date
  // backfillSince: new Date('2023-01-01'), // for initial historical load
});

// result.commits, result.pullRequests, result.issues, result.deployments,
// result.releases, result.workflowRuns, result.contributors, result.languages,
// result.contributorStats, result.reviews, result.deploymentStatuses
// result.errors — per-entity errors, never throws
// result.durationMs — total ingestion time
```

Ingestion tiers (parallel within each tier):
1. Repo metadata (single request)
2. Commits, PRs, issues, deployments, releases, workflow runs, contributors, languages (all parallel)
3. PR reviews — capped at 50 most recent PRs (rate-limit aware)
4. Deployment statuses — capped at 30 most recent deployments
5. Contributor stats (async, may 202 — retried automatically)

---

## Endpoint Registry

File: `src/integrations/github/openapi/endpoint-registry.ts`
Full inventory: `src/integrations/github/openapi/full-endpoint-inventory.json`

Query the registry for metadata about any endpoint:

```ts
import { GITHUB_ENDPOINT_REGISTRY, DevANTCategory } from 'src/integrations/github';

const entry = GITHUB_ENDPOINT_REGISTRY['repos/list-commits'];
// entry.pagination       → true
// entry.cacheable        → true
// entry.webhookRelated   → true (push event replaces polling)
// entry.aiRelevant       → true
// entry.rateLimitRisk    → 'medium'
// entry.enabledForGitHubApps → true
// entry.triggersNotification → false
// entry.primaryUseCase   → 'Commit velocity, author attribution...'
```

`DevANTCategory` values: `repository_intelligence`, `commit_intelligence`,
`pull_request_intelligence`, `issue_intelligence`, `deployment_intelligence`,
`release_intelligence`, `contributor_intelligence`, `webhook_intelligence`,
`security_intelligence`, `activity_timeline`, `dora_metrics`,
`risk_intelligence`, `stakeholder_reporting`, `wallboard_intelligence`,
`sprint_intelligence`.

---

## OpenAPI Spec Facts (do not invent)

- Spec version: 1.1.4, OpenAPI 3.0.3
- Total operations: 1,153 across 765 paths
- 902 operations enabled for GitHub Apps (`x-github.enabledForGitHubApps: true`)
- 199 endpoints return `Link` header for pagination
- 25 endpoints support `since` parameter for incremental sync
- 35 endpoints can return `202 Accepted` (async computing)
- 31 operations are deprecated — avoid them
- 20 operations trigger notification/abuse detection — enforce 3s delay
- No security schemes defined in spec — all endpoints use the same Bearer token auth
- `per_page` default: 30, max: 100 for most endpoints
- `page` default: 1
- Stats endpoints cache for 1 hour — GitHub recomputes them lazily

Never invent endpoint paths, parameter names, response shapes, or status codes.
Always reference `descriptions/api.github.com/api.github.com.json` as the ground truth.
