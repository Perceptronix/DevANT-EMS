import { useMemo, type ReactNode } from 'react'
import {
  CalendarClock,
  ExternalLink,
  FileText,
  GitBranch,
  GitCommit,
  GitPullRequest,
  History,
  Link2,
  Route,
  ShieldAlert,
  UserRound,
  Workflow,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusDot, StatusColor } from '@/components/ui/StatusDot'

interface Props {
  snapshot: any | null
}

interface CommitCard {
  sha: string
  author?: string
  title?: string
  score?: number
  reason?: string
  files: string[]
  deploymentId?: string
  linkedPullRequests: PullRequestCard[]
}

interface DeploymentCard {
  deploymentId: string
  provider?: string
  environment?: string
  sha?: string
  score?: number
  timestamp?: string
  reason?: string
  service?: string
}

interface PullRequestCard {
  number?: number
  title?: string
  author?: string
  state?: string
  url?: string
  fileCount?: number
}

interface TimelineEvent {
  label: string
  timestamp?: string
  detail: string
  kind: 'incident' | 'deployment' | 'commit'
}

function asObject(value: unknown): Record<string, any> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
}

function asArray<T = any>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : []
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function firstString(...values: unknown[]): string | undefined {
  for (const value of values) {
    const candidate = asString(value)
    if (candidate) return candidate
  }
  return undefined
}

function shortSha(value?: string) {
  return value ? value.slice(0, 7) : 'unknown'
}

function scoreLabel(score?: number) {
  if (score === undefined) return '—'
  return `${Math.round(score * 100)}%`
}

function scoreTone(score?: number): StatusColor {
  if (score === undefined) return 'gray'
  if (score >= 0.75) return 'green'
  if (score >= 0.5) return 'yellow'
  return 'red'
}

function formatTime(value?: string) {
  if (!value) return 'No timestamp'
  const parsed = Date.parse(value)
  if (Number.isNaN(parsed)) return value
  return new Date(parsed).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function uniqueStrings(values: Array<string | undefined>): string[] {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value && value.trim()))))
}

function flattenFiles(value: unknown): string[] {
  const files: string[] = []
  for (const item of asArray(value)) {
    if (typeof item === 'string') {
      files.push(item)
      continue
    }
    if (item && typeof item === 'object') {
      const record = item as Record<string, any>
      const path = firstString(record.path, record.filename, record.name, record.file, record.file_path)
      if (path) files.push(path)
      const nested = record.files || record.changed_files || record.suspect_files
      if (nested) files.push(...flattenFiles(nested))
    }
  }
  return uniqueStrings(files)
}

function pickCommitCards(source: any): CommitCard[] {
  const commitSources = [
    source?.commit_correlations,
    source?.incident_commit_correlations,
    source?.linked_commits,
    source?.suspect_commits,
    source?.commit_evidence,
    source?.grounding?.context?.commit_correlations,
    source?.grounding?.hypothesis?.commit_evidence,
  ]

  const cards: CommitCard[] = []
  for (const candidate of commitSources) {
    for (const item of asArray(candidate)) {
      if (typeof item === 'string') {
        cards.push({ sha: item, files: [], linkedPullRequests: [] })
        continue
      }
      if (!item || typeof item !== 'object') continue
      const record = item as Record<string, any>
      const sha = firstString(record.commit_sha, record.sha, record.hash, record.id)
      if (!sha) continue

      const rawPrs = record.linked_pull_requests || record.pull_requests || record.prs || record.pr_links
      const linkedPullRequests = asArray(rawPrs).map((pr) => {
        if (!pr || typeof pr !== 'object') {
          return { title: String(pr) }
        }
        const prRecord = pr as Record<string, any>
        return {
          number: asNumber(prRecord.number),
          title: firstString(prRecord.title, prRecord.name, prRecord.summary, prRecord.message),
          author: firstString(prRecord.author, prRecord.user, prRecord.developer_owner, prRecord.owner),
          state: firstString(prRecord.state, prRecord.status),
          url: firstString(prRecord.url, prRecord.html_url, prRecord.web_url),
          fileCount: asNumber(prRecord.changed_files ?? prRecord.files_changed ?? prRecord.files?.length),
        }
      })

      cards.push({
        sha,
        author: firstString(record.author, record.developer_owner, record.owner, record.committer),
        title: firstString(record.message, record.title, record.summary),
        score: asNumber(record.confidence ?? record.score),
        reason: firstString(record.reason, record.match_reason, record.rationale),
        files: flattenFiles(record.files ?? record.changed_files ?? record.suspect_files),
        deploymentId: firstString(record.deployment_id, record.deployment, record.deployment_sha),
        linkedPullRequests,
      })
    }
  }

  return cards
}

function pickDeploymentCards(source: any): DeploymentCard[] {
  const deploymentSources = [
    source?.deployment_correlations,
    source?.deployment_attribution ? [source.deployment_attribution] : [],
    source?.grounding?.context?.deployment_correlation?.events,
    source?.grounding?.context?.deployment_metadata ? [source.grounding.context.deployment_metadata] : [],
  ]

  const cards: DeploymentCard[] = []
  for (const candidate of deploymentSources) {
    for (const item of asArray(candidate)) {
      if (!item || typeof item !== 'object') continue
      const record = item as Record<string, any>
      const deploymentId = firstString(record.deployment_id, record.id, record.deploymentId, record.deployment_sha)
      if (!deploymentId) continue
      cards.push({
        deploymentId,
        provider: firstString(record.provider, record.deploy_provider),
        environment: firstString(record.environment, record.target, record.env),
        sha: firstString(record.sha, record.commit_sha, record.hash),
        score: asNumber(record.confidence ?? record.score),
        timestamp: firstString(record.timestamp, record.deployed_at, record.created_at, record.at),
        reason: firstString(record.reason, record.notes),
        service: firstString(record.service, record.app, record.project),
      })
    }
  }

  return cards
}

function pickPullRequests(source: any, commitCards: CommitCard[]): PullRequestCard[] {
  const directSources = [
    source?.linked_pull_requests,
    source?.pull_requests,
    source?.prs,
    source?.grounding?.context?.linked_pull_requests,
  ]

  const cards: PullRequestCard[] = []
  for (const candidate of directSources) {
    for (const item of asArray(candidate)) {
      if (!item || typeof item !== 'object') continue
      const record = item as Record<string, any>
      const number = asNumber(record.number)
      const title = firstString(record.title, record.summary, record.message, record.name)
      if (!number && !title) continue
      cards.push({
        number,
        title,
        author: firstString(record.author, record.user, record.owner),
        state: firstString(record.state, record.status),
        url: firstString(record.url, record.html_url, record.web_url),
        fileCount: asNumber(record.changed_files ?? record.files_changed ?? record.files?.length),
      })
    }
  }

  for (const commit of commitCards) {
    for (const pr of commit.linkedPullRequests) {
      cards.push(pr)
    }
  }

  return cards
}

function pickTimeline(snapshot: any, deployments: DeploymentCard[], commitCards: CommitCard[]): TimelineEvent[] {
  const transitions = asArray(snapshot?.transitions)
    .map((transition: any) => {
      const record = asObject(transition)
      return {
        label: firstString(record.state, record.label) ?? 'state',
        timestamp: firstString(record.at, record.timestamp),
        detail: firstString(record.note, record.reason, record.error) ?? 'state change',
        kind: 'incident' as const,
      }
    })

  const deploymentEvents = deployments.slice(0, 5).map((deployment) => ({
    label: deployment.deploymentId,
    timestamp: deployment.timestamp,
    detail: [deployment.provider, deployment.environment, deployment.sha ? `sha ${shortSha(deployment.sha)}` : undefined].filter(Boolean).join(' • ') || 'deployment correlation',
    kind: 'deployment' as const,
  }))

  const commitEvents = commitCards.slice(0, 5).map((commit) => ({
    label: shortSha(commit.sha),
    timestamp: undefined,
    detail: [commit.author, commit.reason, commit.files[0] ? `file ${commit.files[0]}` : undefined].filter(Boolean).join(' • ') || 'commit correlation',
    kind: 'commit' as const,
  }))

  return [...transitions, ...deploymentEvents, ...commitEvents].slice(0, 10)
}

function toneClass(status: StatusColor) {
  switch (status) {
    case 'green': return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
    case 'yellow': return 'border-amber-500/30 bg-amber-500/10 text-amber-200'
    case 'red': return 'border-rose-500/30 bg-rose-500/10 text-rose-200'
    case 'blue': return 'border-sky-500/30 bg-sky-500/10 text-sky-200'
    default: return 'border-white/10 bg-white/5 text-slate-200'
  }
}

export default function GitHubCorrelationDashboard({ snapshot }: Props) {
  const result = snapshot?.result_snapshot ?? {}
  const synthesis = result.operational_brief ?? result.synthesis ?? {}
  const grounding = synthesis.grounding ?? result.grounding ?? {}
  const context = grounding.context ?? {}
  const hypothesis = grounding.hypothesis ?? {}

  const commitCards = useMemo(() => pickCommitCards({ ...result, ...grounding, ...context, ...hypothesis }), [result, grounding, context, hypothesis])
  const deploymentCards = useMemo(() => pickDeploymentCards({ ...result, ...grounding, ...context, ...hypothesis }), [result, grounding, context, hypothesis])
  const pullRequests = useMemo(() => pickPullRequests({ ...result, ...grounding, ...context, ...hypothesis }, commitCards), [result, grounding, context, hypothesis, commitCards])
  const timeline = useMemo(() => pickTimeline(snapshot, deploymentCards, commitCards), [snapshot, deploymentCards, commitCards])

  const likelyCommit = firstString(result.likely_culprit_commit, synthesis.likely_culprit_commit, hypothesis.likely_culprit_commit, commitCards[0]?.sha)
  const likelyOwner = firstString(result.likely_developer_owner, synthesis.likely_developer_owner, hypothesis.likely_developer_owner, commitCards[0]?.author)
  const deploymentAttribution = asObject(result.deployment_attribution ?? synthesis.deployment_attribution ?? hypothesis.deployment_attribution ?? context.deployment_metadata)
  const regressionWarnings = uniqueStrings([
    ...(asArray<string>(result.regression_warnings)),
    ...(asArray<string>(synthesis.regression_warnings)),
    ...(asArray<string>(context.regression_warnings)),
    ...(asArray<string>(hypothesis.regression_warnings)),
  ])
  const suspectFiles = uniqueStrings([
    ...flattenFiles(result.suspect_files),
    ...flattenFiles(synthesis.suspect_files),
    ...flattenFiles(context.suspect_files),
    ...commitCards.flatMap((commit) => commit.files),
  ])
  const overallConfidence = asNumber(result.confidence ?? synthesis.confidence ?? hypothesis.confidence ?? snapshot?.result_snapshot?.operational_confidence)
  const deploymentTiming = asNumber(result.deployment_timing_score ?? synthesis.deployment_timing_score ?? context.deployment_correlation?.score ?? deploymentCards[0]?.score)
  const regressionConfidence = asNumber(result.regression_confidence ?? synthesis.regression_confidence ?? context.regression_probability ?? hypothesis.recurrence_score)
  const linkedPullRequestCount = pullRequests.length
  const incidentTimeline = timeline

  if (!snapshot) return null

  return (
    <section className="relative overflow-hidden rounded-[1.75rem] border border-border/70 bg-card/90 p-6 shadow-[0_30px_120px_rgba(0,0,0,0.35)] backdrop-blur">
      <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(circle_at_top_right,rgba(72,104,184,0.18),transparent_30%),radial-gradient(circle_at_bottom_left,rgba(64,184,131,0.14),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.03),transparent)]" />
      <div className="relative space-y-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="border-border/70 bg-background/50 uppercase tracking-[0.24em] text-[10px] text-muted-foreground">
                GitHub correlation intelligence
              </Badge>
              <Badge variant={regressionWarnings.length ? 'destructive' : 'outline'} className="uppercase tracking-[0.18em] text-[10px]">
                {regressionWarnings.length ? 'regression watch' : 'stable line'}
              </Badge>
              {snapshot?.state && (
                <Badge variant="outline" className="uppercase tracking-[0.18em] text-[10px] text-muted-foreground">
                  {snapshot.state}
                </Badge>
              )}
            </div>
            <div className="space-y-1">
              <h2 className="text-xl font-semibold tracking-tight text-foreground">Repo root cause surface</h2>
              <p className="max-w-3xl text-sm text-muted-foreground">
                Commit → deployment → regression chain. Built for suspect commits, file blame, PR links, and owner attribution.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:min-w-[32rem]">
            <MetricTile label="Confidence" value={scoreLabel(overallConfidence)} tone={scoreTone(overallConfidence)} icon={<ShieldAlert className="h-4 w-4" />} />
            <MetricTile label="Deploy timing" value={scoreLabel(deploymentTiming)} tone={scoreTone(deploymentTiming)} icon={<CalendarClock className="h-4 w-4" />} />
            <MetricTile label="Regression" value={scoreLabel(regressionConfidence)} tone={scoreTone(regressionConfidence)} icon={<History className="h-4 w-4" />} />
            <MetricTile label="Linked PRs" value={String(linkedPullRequestCount || 0)} tone={linkedPullRequestCount ? 'blue' : 'gray'} icon={<GitPullRequest className="h-4 w-4" />} />
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-12">
          <div className="space-y-4 xl:col-span-7">
            <Card className="border-border/70 bg-background/60">
              <CardHeader className="pb-4">
                <CardTitle className="flex items-center gap-2">
                  <GitCommit className="h-4 w-4 text-primary" />
                  Suspect commits
                </CardTitle>
                <CardDescription>Highest-signal commit cards from correlation engine.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {commitCards.length > 0 ? commitCards.slice(0, 4).map((commit) => (
                  <div key={commit.sha} className="rounded-2xl border border-border/60 bg-card/70 p-4 transition-colors hover:border-primary/30">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className="font-mono text-[10px] uppercase tracking-[0.18em]">
                            {shortSha(commit.sha)}
                          </Badge>
                          {typeof commit.score === 'number' && (
                            <Badge variant="outline" className={toneClass(scoreTone(commit.score))}>
                              {scoreLabel(commit.score)}
                            </Badge>
                          )}
                          {commit.deploymentId && (
                            <Badge variant="outline" className="border-sky-500/30 bg-sky-500/10 text-sky-200">
                              deploy {commit.deploymentId}
                            </Badge>
                          )}
                        </div>
                        <div className="space-y-1">
                          <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
                            <span>{commit.title || 'Commit match'}</span>
                            {commit.author && (
                              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                                <UserRound className="h-3.5 w-3.5" />
                                {commit.author}
                              </span>
                            )}
                          </div>
                          {commit.reason && <p className="text-xs text-muted-foreground">{commit.reason}</p>}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <GitBranch className="h-4 w-4" />
                        {commit.files.length} changed file{commit.files.length === 1 ? '' : 's'}
                      </div>
                    </div>

                    {commit.files.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {commit.files.slice(0, 4).map((file) => (
                          <Badge key={file} variant="outline" className="border-border/70 bg-background/80 font-mono text-[10px]">
                            {file}
                          </Badge>
                        ))}
                        {commit.files.length > 4 && (
                          <Badge variant="outline" className="border-border/60 bg-muted/40 text-muted-foreground">
                            +{commit.files.length - 4} more
                          </Badge>
                        )}
                      </div>
                    )}

                    {commit.linkedPullRequests.length > 0 && (
                      <div className="mt-3 space-y-2 border-t border-border/50 pt-3">
                        <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-muted-foreground">
                          <Link2 className="h-3.5 w-3.5" />
                          linked pull requests
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {commit.linkedPullRequests.slice(0, 3).map((pr, index) => (
                            <Badge key={`${commit.sha}-pr-${index}`} variant="outline" className="border-border/70 bg-background/80 text-xs">
                              #{pr.number ?? 'PR'} {pr.title ?? pr.author ?? 'linked'}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )) : (
                  <EmptyState icon={<GitCommit className="h-4 w-4" />} title="No commit match" description="Root cause context did not surface commit candidates yet." />
                )}
              </CardContent>
            </Card>

            <Card className="border-border/70 bg-background/60">
              <CardHeader className="pb-4">
                <CardTitle className="flex items-center gap-2">
                  <Workflow className="h-4 w-4 text-primary" />
                  Deployment timeline
                </CardTitle>
                <CardDescription>Recent deployment attribution and timing.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {deploymentCards.length > 0 ? deploymentCards.slice(0, 5).map((deployment) => (
                  <div key={deployment.deploymentId} className="flex items-start gap-3 rounded-2xl border border-border/60 bg-card/70 p-4">
                    <div className="mt-0.5 rounded-full border border-border/70 bg-background p-2">
                      <Route className="h-3.5 w-3.5 text-primary" />
                    </div>
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-foreground">{deployment.deploymentId}</span>
                        {deployment.provider && <Badge variant="outline" className="text-[10px] uppercase tracking-[0.16em]">{deployment.provider}</Badge>}
                        {deployment.environment && <Badge variant="outline" className="text-[10px] uppercase tracking-[0.16em]">{deployment.environment}</Badge>}
                        {typeof deployment.score === 'number' && <Badge variant="outline" className={toneClass(scoreTone(deployment.score))}>{scoreLabel(deployment.score)}</Badge>}
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {deployment.reason || 'Timing and service match used for correlation.'}
                      </p>
                      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                        <span>{formatTime(deployment.timestamp)}</span>
                        {deployment.sha && <span>sha {shortSha(deployment.sha)}</span>}
                        {deployment.service && <span>{deployment.service}</span>}
                      </div>
                    </div>
                  </div>
                )) : (
                  <EmptyState icon={<Workflow className="h-4 w-4" />} title="No deployment match" description="No recent deployment correlation surfaced for this run." />
                )}
              </CardContent>
            </Card>
          </div>

          <div className="space-y-4 xl:col-span-5">
            <Card className="border-border/70 bg-background/60">
              <CardHeader className="pb-4">
                <CardTitle className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-primary" />
                  Changed files
                </CardTitle>
                <CardDescription>Suspect file viewer from commit and regression signals.</CardDescription>
              </CardHeader>
              <CardContent>
                {suspectFiles.length > 0 ? (
                  <div className="max-h-72 overflow-auto rounded-2xl border border-border/60 bg-card/70 p-3">
                    <div className="space-y-2">
                      {suspectFiles.slice(0, 12).map((file, index) => (
                        <div key={`${file}-${index}`} className="flex items-start gap-3 rounded-xl border border-transparent px-2 py-2 hover:border-border/60 hover:bg-muted/20">
                          <div className="mt-1 rounded-full bg-primary/10 p-1.5">
                            <FileText className="h-3.5 w-3.5 text-primary" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="truncate font-mono text-xs text-foreground">{file}</div>
                            <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">candidate file</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <EmptyState icon={<FileText className="h-4 w-4" />} title="No suspect files" description="File-level blame not yet resolved." />
                )}
              </CardContent>
            </Card>

            <Card className="border-border/70 bg-background/60">
              <CardHeader className="pb-4">
                <CardTitle className="flex items-center gap-2">
                  <History className="h-4 w-4 text-primary" />
                  Regression badges
                </CardTitle>
                <CardDescription>Repeat-failure signals and warnings.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <Badge variant={regressionWarnings.length ? 'destructive' : 'outline'}>
                    {regressionWarnings.length ? `${regressionWarnings.length} warnings` : 'No warning'}
                  </Badge>
                  {firstString(result.regression_type, synthesis.regression_type, hypothesis.regression_type) && (
                    <Badge variant="outline" className="uppercase tracking-[0.18em] text-[10px]">
                      {firstString(result.regression_type, synthesis.regression_type, hypothesis.regression_type)?.replace(/_/g, ' ')}
                    </Badge>
                  )}
                  {firstString(result.likely_culprit_commit, synthesis.likely_culprit_commit, hypothesis.likely_culprit_commit) && (
                    <Badge variant="outline" className="font-mono text-[10px]">
                      culprit {shortSha(firstString(result.likely_culprit_commit, synthesis.likely_culprit_commit, hypothesis.likely_culprit_commit))}
                    </Badge>
                  )}
                </div>
                {regressionWarnings.length > 0 ? (
                  <div className="space-y-2">
                    {regressionWarnings.slice(0, 4).map((warning, index) => (
                      <div key={`${warning}-${index}`} className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-sm text-amber-100">
                        {warning}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-xl border border-border/60 bg-card/60 p-3 text-sm text-muted-foreground">
                    No regression warning surfaced.
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="border-border/70 bg-background/60">
              <CardHeader className="pb-4">
                <CardTitle className="flex items-center gap-2">
                  <UserRound className="h-4 w-4 text-primary" />
                  Developer attribution
                </CardTitle>
                <CardDescription>Owner, blame, and commit-level signal.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <MiniField label="Likely owner" value={likelyOwner} icon={<UserRound className="h-4 w-4" />} />
                  <MiniField label="Likely commit" value={likelyCommit ? shortSha(likelyCommit) : undefined} icon={<GitCommit className="h-4 w-4" />} mono />
                </div>
                <div className="rounded-2xl border border-border/60 bg-card/70 p-4">
                  <div className="flex items-center justify-between text-xs uppercase tracking-[0.18em] text-muted-foreground">
                    <span>Deployment attribution</span>
                    <StatusDot status={scoreTone(asNumber(deploymentAttribution.score))} />
                  </div>
                  <div className="mt-3 space-y-2 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-muted-foreground">Deployment</span>
                      <span className="font-mono text-xs">{firstString(deploymentAttribution.deployment_id, deploymentAttribution.id) ?? 'unknown'}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-muted-foreground">Provider</span>
                      <span>{firstString(deploymentAttribution.provider, deploymentAttribution.deploy_provider) ?? 'unknown'}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-muted-foreground">Environment</span>
                      <span>{firstString(deploymentAttribution.environment, deploymentAttribution.target) ?? 'unknown'}</span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="border-border/70 bg-background/60">
              <CardHeader className="pb-4">
                <CardTitle className="flex items-center gap-2">
                  <GitPullRequest className="h-4 w-4 text-primary" />
                  Linked pull requests
                </CardTitle>
                <CardDescription>PRs tied to suspect commits and deployment window.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {pullRequests.length > 0 ? pullRequests.slice(0, 5).map((pr, index) => (
                  <div key={`${pr.number ?? pr.title ?? index}`} className="flex items-start gap-3 rounded-2xl border border-border/60 bg-card/70 p-3">
                    <div className="mt-0.5 rounded-full border border-border/60 bg-background p-1.5">
                      <GitPullRequest className="h-3.5 w-3.5 text-primary" />
                    </div>
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-sm">{pr.title || `PR ${pr.number ?? ''}`}</span>
                        {pr.state && <Badge variant="outline" className="text-[10px] uppercase tracking-[0.18em]">{pr.state}</Badge>}
                      </div>
                      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                        {pr.author && <span>by {pr.author}</span>}
                        {typeof pr.fileCount === 'number' && <span>{pr.fileCount} files</span>}
                        {pr.url && (
                          <a href={pr.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                            open <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                )) : (
                  <EmptyState icon={<GitPullRequest className="h-4 w-4" />} title="No linked PRs" description="Pull request links not present in run payload." />
                )}
              </CardContent>
            </Card>

            <Card className="border-border/70 bg-background/60">
              <CardHeader className="pb-4">
                <CardTitle className="flex items-center gap-2">
                  <CalendarClock className="h-4 w-4 text-primary" />
                  Incident timeline
                </CardTitle>
                <CardDescription>Run transitions plus commit and deployment moments.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {incidentTimeline.length > 0 ? incidentTimeline.map((event, index) => (
                  <div key={`${event.kind}-${event.label}-${index}`} className="flex items-start gap-3 rounded-2xl border border-border/60 bg-card/70 p-3">
                    <StatusDot status={event.kind === 'deployment' ? 'blue' : event.kind === 'commit' ? 'yellow' : 'green'} className="mt-1" />
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-sm font-medium text-foreground">{event.label}</span>
                        <span className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">{event.kind}</span>
                      </div>
                      <div className="text-xs text-muted-foreground">{event.detail}</div>
                      <div className="text-[11px] text-muted-foreground/80">{formatTime(event.timestamp)}</div>
                    </div>
                  </div>
                )) : (
                  <EmptyState icon={<CalendarClock className="h-4 w-4" />} title="No timeline" description="Incident timeline not available yet." />
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </section>
  )
}

function MetricTile({ label, value, tone, icon }: { label: string; value: string; tone: StatusColor; icon: ReactNode }) {
  return (
    <div className={`rounded-2xl border p-3 ${toneClass(tone)}`}>
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-muted-foreground/80">
        {icon}
        <span>{label}</span>
      </div>
      <div className="mt-2 text-lg font-semibold tracking-tight text-foreground">{value}</div>
    </div>
  )
}

function MiniField({ label, value, icon, mono = false }: { label: string; value?: string; icon: ReactNode; mono?: boolean }) {
  return (
    <div className="rounded-2xl border border-border/60 bg-card/70 p-3">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {icon}
        <span>{label}</span>
      </div>
      <div className={`mt-2 truncate text-sm font-medium ${mono ? 'font-mono' : ''}`}>{value ?? 'unknown'}</div>
    </div>
  )
}

function EmptyState({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-border/70 bg-background/50 p-4 text-sm text-muted-foreground">
      <div className="flex items-center gap-2 text-foreground">
        {icon}
        <span className="font-medium">{title}</span>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">{description}</p>
    </div>
  )
}
