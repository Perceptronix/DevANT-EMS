import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronRight, Search, Square } from 'lucide-react'

import PipelineTimeline from '@/components/PipelineTimeline'
import useSSE from '@/hooks/useSSE'
import { Button } from '@/components/ui/button'
import { StatusDot, StatusColor } from '@/components/ui/StatusDot'
import { isTerminalState, shouldApplySnapshot } from '@/lib/runSnapshot'

type JobState =
  | 'PENDING'
  | 'INITIALIZING'
  | 'INGESTING'
  | 'ANALYZING'
  | 'SCORING'
  | 'FINALIZING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

interface Synthesis {
  operational_summary?: string
  root_cause?: string
  repository_type?: string
  affected_services?: string[]
  detected_strengths?: string[]
  detected_gaps?: string[]
  deployment_risks?: string[]
  monitoring_risks?: string[]
  rollback_confidence?: string
  recommended_actions?: string[]
  operational_confidence?: number
  final_assessment?: string
  severity?: string
  health_state?: string
  human_summary?: string
  // legacy fields
  main_risks?: string[]
  confidence_explanation?: string
}

interface RunSnapshot {
  run_id: string
  repo_url: string
  state: JobState
  transitions: Array<{ state: JobState; at: string; note?: string }>
  partial?: Record<string, unknown>
  result_snapshot?: {
    scanned?: boolean
    error?: string | null
    evidence?: Record<string, unknown>
    topology?: { services?: Array<{ name?: string; path?: string }>; edges?: Array<{ from: string; to: string }> }
    scores?: Record<string, number>
    synthesis?: Synthesis | null
  } | null
  error?: string | null
}



function stateStatusColor(state: JobState | undefined): StatusColor {
  if (!state) return 'gray'
  if (state === 'COMPLETED') return 'green'
  if (state === 'FAILED') return 'red'
  if (state === 'CANCELLED') return 'gray'
  return 'blue'
}

export default function App() {
  const [repoUrl, setRepoUrl] = useState('')
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [activeSnapshot, setActiveSnapshot] = useState<RunSnapshot | null>(null)
  const [recentRuns, setRecentRuns] = useState<RunSnapshot[]>([])
  const [isStarting, setIsStarting] = useState(false)
  const [streamConnected, setStreamConnected] = useState(false)
  const [backendConnection, setBackendConnection] = useState<'unknown' | 'checking' | 'connected' | 'disconnected'>('unknown')

  const latestTransitionCountRef = useRef<number>(0)

  const refreshRecent = useCallback(async () => {
    try {
      const res = await fetch('/api/analyze-repository?limit=20')
      if (!res.ok) return
      const data = await res.json() as { runs: RunSnapshot[] }
      setRecentRuns(data.runs || [])
    } catch {
      // noop
    }
  }, [])

  const checkBackendConnection = useCallback(async () => {
    setBackendConnection('checking')
    try {
      const response = await fetch('/api/config')
      if (!response.ok) {
        setBackendConnection('disconnected')
        return
      }
      const payload = await response.json().catch(() => null)
      if (payload?.airweave_configured !== undefined) {
        setBackendConnection('connected')
      } else {
        setBackendConnection('disconnected')
      }
    } catch {
      setBackendConnection('disconnected')
    }
  }, [])

  useEffect(() => {
    void refreshRecent()
  }, [refreshRecent])

  useEffect(() => {
    void checkBackendConnection()
  }, [checkBackendConnection])

  const applySnapshot = useCallback((incoming: RunSnapshot) => {
    setActiveSnapshot((prev) => {
      const count = incoming.transitions?.length ?? 0
      const current = latestTransitionCountRef.current
      const currentState = prev?.state

      if (!shouldApplySnapshot(prev, incoming)) return prev
      if (count < current) return prev
      if (isTerminalState(currentState)) return prev

      latestTransitionCountRef.current = count
      return incoming
    })
  }, [])

  const { connected: hookConnected, close: hookClose } = useSSE(activeRunId ? `/api/analyze-repository/${activeRunId}/stream` : undefined, applySnapshot)

  const closeStream = useCallback(() => {
    hookClose()
    setStreamConnected(false)
  }, [hookClose])

  const connectStream = useCallback(() => {
    // no-op: useSSE auto-connects when activeRunId set
    setStreamConnected(true)
  }, [])

  useEffect(() => () => closeStream(), [closeStream])

  // Handle terminal state separately to avoid circular dependencies
  useEffect(() => {
    if (activeSnapshot && isTerminalState(activeSnapshot.state)) {
      closeStream()
      void refreshRecent()
      if (activeSnapshot.state === 'CANCELLED') {
        setActiveRunId(null)
      }
    }
  }, [activeSnapshot?.state, closeStream, refreshRecent])

  useEffect(() => {
    // mirror hook-connected into UI badge and debug panel
    setStreamConnected(Boolean(hookConnected))
  }, [hookConnected])



  const startAnalysis = useCallback(async () => {
    if (!repoUrl.trim()) return
    setIsStarting(true)
    latestTransitionCountRef.current = 0
    setActiveSnapshot(null)

    try {
      const res = await fetch('/api/analyze-repository', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl.trim() }),
      })
      if (!res.ok) throw new Error('start_failed')
      const data = await res.json() as { run_id: string }
      setActiveRunId(data.run_id)
      connectStream()
      void refreshRecent()
    } finally {
      setIsStarting(false)
    }
  }, [repoUrl, connectStream, refreshRecent])

  const cancelAnalysis = useCallback(async () => {
    if (!activeRunId) return
    await fetch(`/api/analyze-repository/${activeRunId}/cancel`, { method: 'POST' })
  }, [activeRunId])

  const { scores, evidence, topology } = useMemo(() => {
    if (activeSnapshot?.result_snapshot) {
      return {
        scores: activeSnapshot.result_snapshot.scores,
        evidence: activeSnapshot.result_snapshot.evidence as Record<string, unknown>,
        topology: activeSnapshot.result_snapshot.topology,
      }
    }
    
    // Compute from partials in realtime
    const partials = activeSnapshot?.partial || {}
    let computedScores: Record<string, number> | undefined = undefined
    let computedEvidence: Record<string, unknown> = {}
    let computedTopology: any = undefined
    
    Object.values(partials).forEach((p: any) => {
      // Orchestrator now emits under 'evidence' key
      const ev = p?.evidence || p?.progress || {}

      if (ev.scores) computedScores = { ...computedScores, ...ev.scores }

      const toArr = (v: any) => Array.isArray(v) ? v : new Array(typeof v === 'number' ? v : 0).fill(null)
      if (ev.dockerfiles !== undefined) computedEvidence.dockerfiles = toArr(ev.dockerfiles)
      if (ev.kubernetes_manifests !== undefined) computedEvidence.kubernetes_manifests = toArr(ev.kubernetes_manifests)
      if (ev.helm_charts !== undefined) computedEvidence.helm_charts = toArr(ev.helm_charts)
      if (ev.terraform !== undefined) computedEvidence.terraform = toArr(ev.terraform)
      if (ev.workflow_count !== undefined) computedEvidence.workflows = new Array(ev.workflow_count).fill(null)
      if (ev.workflows !== undefined && Array.isArray(ev.workflows)) computedEvidence.workflows = ev.workflows
      if (ev.prometheus !== undefined) computedEvidence.prometheus = ev.prometheus
      if (ev.otel !== undefined) computedEvidence.otel = ev.otel

      // Live error clusters from both old and new field names
      if (ev.clusters) computedEvidence.live_errors = ev.clusters
      if (ev.live_errors) computedEvidence.live_errors = ev.live_errors

      if (ev.topology) computedTopology = ev.topology
      if (ev.repo_type) computedEvidence.repo_type = ev.repo_type
      if (ev.primary_language) computedEvidence.primary_language = ev.primary_language
      if (ev.commits !== undefined) computedEvidence.recent_commits = ev.commits
      if (ev.prs !== undefined) computedEvidence.recent_prs = ev.prs
    })

    return { scores: computedScores, evidence: computedEvidence, topology: computedTopology }
  }, [activeSnapshot])



  const synthesis = activeSnapshot?.result_snapshot?.synthesis as Synthesis | null | undefined
  const healthColor: StatusColor =
    synthesis?.health_state === 'Healthy' ? 'green'
    : synthesis?.health_state === 'Critical' ? 'red'
    : synthesis?.health_state === 'Degraded' ? 'yellow'
    : activeSnapshot?.state === 'FAILED' ? 'red'
    : activeSnapshot?.state ? 'blue' : 'gray'

  const stateLabel: Record<string, string> = {
    PENDING: 'Waiting', INITIALIZING: 'Starting up', INGESTING: 'Scanning repository',
    ANALYZING: 'Understanding structure', SCORING: 'Assessing health',
    FINALIZING: 'Generating brief', COMPLETED: 'Complete', FAILED: 'Failed', CANCELLED: 'Cancelled',
  }

  return (
    <div className="min-h-screen bg-background text-foreground font-sans">
      {/* Header */}
      <header className="border-b border-border bg-card/50 backdrop-blur sticky top-0 z-10">
        <div className="container mx-auto px-6 py-3 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-sm font-semibold tracking-tight">DevANT <span className="text-muted-foreground font-normal">AI Operational Assistant</span></h1>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <div className="flex items-center gap-1.5">
              <StatusDot status={backendConnection === 'connected' ? 'green' : backendConnection === 'disconnected' ? 'red' : 'gray'} />
              <span className="text-muted-foreground cursor-pointer hover:text-foreground" onClick={checkBackendConnection}>
                {backendConnection === 'checking' ? 'Checking...' : backendConnection === 'connected' ? 'Ready' : 'Disconnected'}
              </span>
            </div>
            {activeRunId && (
              <div className="flex items-center gap-1.5">
                <StatusDot status={streamConnected ? 'blue' : 'gray'} animate={streamConnected} />
                <span className="text-muted-foreground">{streamConnected ? 'Live' : 'Connecting...'}</span>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="container mx-auto px-6 py-8 max-w-5xl space-y-6">
        {/* Input bar */}
        <section className="flex flex-col sm:flex-row gap-3">
          <input
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && startAnalysis()}
            placeholder="https://github.com/org/repo"
            className="flex-1 h-10 rounded-md bg-card border border-border px-3 text-sm outline-none focus:border-primary transition-colors"
          />
          <Button onClick={startAnalysis} disabled={isStarting || !repoUrl.trim()} className="bg-primary text-primary-foreground hover:bg-primary/90">
            <Search className="h-4 w-4 mr-2" />
            {isStarting ? 'Starting...' : 'Analyze'}
          </Button>
          <Button variant="outline" onClick={cancelAnalysis} disabled={!activeRunId || isTerminalState(activeSnapshot?.state)} className="border-border hover:bg-muted">
            <Square className="h-4 w-4 mr-2" />Cancel
          </Button>
        </section>

        {/* Status bar */}
        {activeSnapshot && (
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <StatusDot status={healthColor} animate={activeSnapshot.state === 'ANALYZING' || activeSnapshot.state === 'INGESTING' || activeSnapshot.state === 'SCORING' || activeSnapshot.state === 'FINALIZING'} />
              <span>{stateLabel[activeSnapshot.state] ?? activeSnapshot.state}</span>
            </div>
            <span className="text-border">•</span>
            <span className="truncate max-w-xs">{activeSnapshot.repo_url}</span>
            {activeRunId && <span className="text-border ml-auto font-mono">{activeRunId.slice(0, 8)}</span>}
          </div>
        )}

        {/* ── SECTION 1: AI Operational Brief ── */}
        {synthesis ? (
          <section className="bg-card border border-border rounded-xl p-6 space-y-6 shadow-sm">
            {/* Brief header */}
            <div className="flex items-start justify-between gap-4 border-b border-border/50 pb-5">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <StatusDot status={healthColor} />
                  <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{synthesis.health_state ?? 'Unknown'}</span>
                  {synthesis.repository_type && (
                    <span className="text-xs bg-muted px-2 py-0.5 rounded text-muted-foreground">{synthesis.repository_type.replace(/_/g, ' ')}</span>
                  )}
                </div>
                <p className="text-base font-medium leading-snug">{synthesis.human_summary}</p>
              </div>
              {synthesis.severity && (
                <span className={`shrink-0 text-xs font-semibold px-3 py-1 rounded-full ${
                  synthesis.severity === 'Critical' ? 'bg-red-500/15 text-red-400' :
                  synthesis.severity === 'High' ? 'bg-orange-500/15 text-orange-400' :
                  synthesis.severity === 'Medium' ? 'bg-yellow-500/15 text-yellow-400' :
                  'bg-green-500/15 text-green-400'
                }`}>{synthesis.severity}</span>
              )}
            </div>

            {/* Summary + Root Cause */}
            <div className="space-y-4">
              {synthesis.operational_summary && (
                <div>
                  <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-1.5">Situation</h3>
                  <p className="text-sm leading-relaxed">{synthesis.operational_summary}</p>
                </div>
              )}
              {synthesis.root_cause && (
                <div>
                  <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-1.5">Root Cause</h3>
                  <p className="text-sm leading-relaxed text-muted-foreground">{synthesis.root_cause}</p>
                </div>
              )}
            </div>

            {/* Strengths + Gaps grid */}
            {((synthesis.detected_strengths?.length ?? 0) > 0 || (synthesis.detected_gaps?.length ?? 0) > 0) && (
              <div className="grid sm:grid-cols-2 gap-4 pt-2 border-t border-border/50">
                {(synthesis.detected_strengths?.length ?? 0) > 0 && (
                  <div>
                    <h3 className="text-xs font-medium text-green-500 uppercase tracking-wider mb-2">What's in place</h3>
                    <ul className="space-y-1.5 text-sm text-muted-foreground">
                      {synthesis.detected_strengths!.map((s, i) => (
                        <li key={i} className="flex items-start gap-2"><span className="text-green-500 mt-0.5">✓</span>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {(synthesis.detected_gaps?.length ?? 0) > 0 && (
                  <div>
                    <h3 className="text-xs font-medium text-yellow-500 uppercase tracking-wider mb-2">What's missing</h3>
                    <ul className="space-y-1.5 text-sm text-muted-foreground">
                      {synthesis.detected_gaps!.map((g, i) => (
                        <li key={i} className="flex items-start gap-2"><span className="text-yellow-500 mt-0.5">✗</span>{g}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Recommended Actions */}
            {(synthesis.recommended_actions?.length ?? 0) > 0 && (
              <div className="pt-2 border-t border-border/50">
                <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">Recommended Actions</h3>
                <ol className="space-y-2">
                  {synthesis.recommended_actions!.map((a, i) => (
                    <li key={i} className="flex items-start gap-3 text-sm">
                      <span className="shrink-0 w-5 h-5 rounded-full bg-primary/10 text-primary text-xs font-medium flex items-center justify-center mt-0.5">{i + 1}</span>
                      <span>{a}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}

            {/* Confidence footer */}
            {typeof synthesis.operational_confidence === 'number' && (
              <div className="flex items-center justify-between text-xs text-muted-foreground pt-2 border-t border-border/50">
                <span>AI Confidence</span>
                <div className="flex items-center gap-3">
                  <div className="w-24 h-1.5 rounded-full bg-muted overflow-hidden">
                    <div className="h-full bg-primary transition-all" style={{ width: `${Math.round(synthesis.operational_confidence * 100)}%` }} />
                  </div>
                  <span className="font-medium tabular-nums">{Math.round(synthesis.operational_confidence * 100)}%</span>
                </div>
              </div>
            )}
          </section>
        ) : activeSnapshot && !isTerminalState(activeSnapshot.state) ? (
          <section className="bg-card border border-border rounded-xl p-8 text-center space-y-3">
            <div className="flex justify-center">
              <StatusDot status="blue" animate />
            </div>
            <p className="text-sm font-medium">{stateLabel[activeSnapshot.state] ?? activeSnapshot.state}</p>
            <p className="text-xs text-muted-foreground">AI brief will appear here when analysis completes</p>
          </section>
        ) : activeSnapshot?.state === 'FAILED' ? (
          <section className="bg-card border border-red-500/30 rounded-xl p-6 space-y-2">
            <div className="flex items-center gap-2">
              <StatusDot status="red" />
              <span className="font-medium text-sm">Analysis failed</span>
            </div>
            <p className="text-sm text-muted-foreground">{activeSnapshot.error ?? 'An unexpected error occurred during analysis.'}</p>
          </section>
        ) : null}

        {/* ── SECTION 2: Active Operational Incidents ── */}
        {Array.isArray(evidence?.live_errors) && (evidence.live_errors as any[]).length > 0 && (
          <section className="bg-card border border-border rounded-xl p-6 space-y-4 shadow-sm">
            <div className="flex items-center justify-between border-b border-border/50 pb-4">
              <div>
                <h2 className="font-semibold">Active Incidents</h2>
                <p className="text-xs text-muted-foreground mt-0.5">Clustered from live operational signals</p>
              </div>
              <span className="text-xs font-medium bg-red-500/10 text-red-400 px-2.5 py-1 rounded-full">
                {(evidence.live_errors as any[]).length} active
              </span>
            </div>
            <div className="space-y-3">
              {(evidence.live_errors as any[]).map((cluster: any, i: number) => {
                const isHigh = cluster.error_type === 'critical' || cluster.error_type === 'high' ||
                  cluster.severity === 'S1' || cluster.severity === 'S2' ||
                  (cluster.error_count ?? 0) >= 5
                return (
                  <div key={i} className="rounded-lg border border-border/60 bg-background p-4 space-y-2 hover:border-border transition-colors">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-2 min-w-0">
                        <StatusDot status={isHigh ? 'red' : 'yellow'} />
                        <span className="font-medium text-sm truncate">{cluster.signature || cluster.title || 'Unknown issue'}</span>
                      </div>
                      <span className="shrink-0 text-xs text-muted-foreground">{cluster.error_count ?? 1} occurrences</span>
                    </div>
                    {(cluster.modules?.length > 0 || cluster.affected_orgs?.length > 0) && (
                      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground pl-5">
                        {cluster.modules?.slice(0, 3).map((m: string, j: number) => (
                          <span key={j} className="bg-muted px-2 py-0.5 rounded font-mono">{m}</span>
                        ))}
                        {cluster.affected_orgs?.length > 0 && (
                          <span className="text-muted-foreground/70">• {cluster.affected_orgs.slice(0, 2).join(', ')}</span>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </section>
        )}

        {/* Affected services from synthesis */}
        {synthesis && (synthesis.affected_services?.length ?? 0) > 0 && (
          <section className="bg-card border border-border rounded-xl p-6 space-y-4">
            <div className="grid sm:grid-cols-2 gap-6">
              <div>
                <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">Affected Services</h3>
                <div className="flex flex-wrap gap-2">
                  {synthesis.affected_services!.map((svc, i) => (
                    <span key={i} className="text-xs bg-muted px-2.5 py-1 rounded-md font-mono">{svc}</span>
                  ))}
                </div>
              </div>
              {synthesis.rollback_confidence && (
                <div>
                  <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">Rollback Safety</h3>
                  <div className="flex items-center gap-2">
                    <StatusDot status={synthesis.rollback_confidence === 'high' ? 'green' : synthesis.rollback_confidence === 'medium' ? 'yellow' : 'red'} />
                    <span className="text-sm capitalize">{synthesis.rollback_confidence} confidence</span>
                  </div>
                </div>
              )}
            </div>
            {((synthesis.deployment_risks?.length ?? 0) > 0 || (synthesis.monitoring_risks?.length ?? 0) > 0) && (
              <div className="grid sm:grid-cols-2 gap-4 pt-4 border-t border-border/50">
                {(synthesis.deployment_risks?.length ?? 0) > 0 && (
                  <div>
                    <h3 className="text-xs font-medium text-orange-400 uppercase tracking-wider mb-2">Deployment Risk</h3>
                    <ul className="space-y-1.5 text-sm text-muted-foreground">
                      {synthesis.deployment_risks!.map((r, i) => <li key={i}>• {r}</li>)}
                    </ul>
                  </div>
                )}
                {(synthesis.monitoring_risks?.length ?? 0) > 0 && (
                  <div>
                    <h3 className="text-xs font-medium text-blue-400 uppercase tracking-wider mb-2">Monitoring Coverage</h3>
                    <ul className="space-y-1.5 text-sm text-muted-foreground">
                      {synthesis.monitoring_risks!.map((r, i) => <li key={i}>• {r}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {/* ── SECTION 3: Internal Evidence (collapsible) ── */}
        {activeSnapshot && (
          <details className="group border border-border rounded-xl bg-card overflow-hidden">
            <summary className="flex items-center justify-between p-4 cursor-pointer list-none hover:bg-muted/30 transition-colors">
              <span className="text-sm font-medium">Internal Evidence</span>
              <ChevronRight className="h-4 w-4 text-muted-foreground group-open:rotate-90 transition-transform" />
            </summary>
            <div className="p-5 pt-0 border-t border-border/50 space-y-5 mt-1">
              {/* Repository overview */}
              <div className="grid sm:grid-cols-2 gap-4 pt-4">
                <div className="space-y-2">
                  <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Infrastructure Found</h3>
                  <EvidenceSummary evidence={evidence} />
                </div>
                <div className="space-y-2">
                  <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Service Map</h3>
                  <div className="rounded-md border border-border bg-background p-3 text-xs space-y-1">
                    <div className="text-muted-foreground">{topology?.services?.length ?? 0} services · {topology?.edges?.length ?? 0} connections</div>
                    {(topology?.edges?.length ?? 0) > 0 && (
                      <div className="max-h-36 overflow-auto space-y-0.5 mt-2">
                        {topology?.edges?.map((edge: any, idx: number) => (
                          <div key={idx} className="font-mono text-muted-foreground/80">{edge.from} → {edge.to}</div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Health scores */}
              {scores && (
                <div>
                  <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">Health Scores</h3>
                  <div className="space-y-1">
                    <ScoreRow name="Production Readiness" score={scores.production_readiness} />
                    <ScoreRow name="Deployment Setup" score={scores.deployment_maturity} />
                    <ScoreRow name="Monitoring Coverage" score={scores.observability_readiness} />
                    <ScoreRow name="Rollback Safety" score={scores.rollback_safety} />
                    <ScoreRow name="Service Connections" score={scores.topology_resilience} />
                  </div>
                </div>
              )}

              {/* Run timeline */}
              <div>
                <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">Analysis Timeline</h3>
                <PipelineTimeline snapshot={activeSnapshot} />
              </div>
            </div>
          </details>
        )}

        {/* Recent Analyses */}
        {recentRuns.length > 0 && (
          <section className="space-y-2">
            <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Recent Analyses</h2>
            <div className="space-y-1.5 max-h-48 overflow-auto">
              {recentRuns.map((run) => (
                <button
                  key={run.run_id}
                  className="w-full text-left flex items-center justify-between rounded-lg border border-border px-3 py-2 bg-card hover:bg-muted/50 transition-colors text-sm"
                  onClick={() => {
                    setActiveRunId(run.run_id)
                    latestTransitionCountRef.current = run.transitions?.length ?? 0
                    setActiveSnapshot(run)
                    setRepoUrl(run.repo_url)
                    if (!isTerminalState(run.state)) connectStream()
                  }}
                >
                  <span className="truncate mr-4 text-muted-foreground">{run.repo_url}</span>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-muted-foreground/60">{run.state}</span>
                    <StatusDot status={stateStatusColor(run.state)} />
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  )
}






function ScoreRow({ name, score }: { name: string; score: number | undefined }) {
  const display = score === undefined ? '-' : `${Math.round(score * 100)}%`
  const status: StatusColor = score === undefined ? 'gray' : score >= 0.7 ? 'green' : score >= 0.45 ? 'yellow' : 'red'
  return (
    <div className="flex items-center justify-between text-sm py-1 border-b border-border/50 last:border-0">
      <span>{name}</span>
      <div className="flex items-center gap-3">
        <StatusDot status={status} />
        <span className="tabular-nums w-8 text-right font-medium">{display}</span>
      </div>
    </div>
  )
}

function EvidenceRow({ name, present }: { name: string; present: boolean }) {
  return (
    <div className="flex items-center justify-between text-sm py-1.5">
      <span>{name}</span>
      <div className="flex items-center gap-2">
        <StatusDot status={present ? 'green' : 'gray'} />
        <span className="text-xs text-muted-foreground">{present ? 'found' : 'missing'}</span>
      </div>
    </div>
  )
}

function EvidenceSummary({ evidence }: { evidence: Record<string, unknown> | undefined }) {
  const items = [
    { name: 'CI/CD Workflows', present: ((evidence?.workflows as unknown[] | undefined)?.length ?? 0) > 0 },
    { name: 'Docker', present: ((evidence?.dockerfiles as unknown[] | undefined)?.length ?? 0) > 0 },
    { name: 'Kubernetes', present: ((evidence?.kubernetes_manifests as unknown[] | undefined)?.length ?? 0) > 0 },
    { name: 'Terraform', present: ((evidence?.terraform as unknown[] | undefined)?.length ?? 0) > 0 },
    { name: 'Helm Charts', present: ((evidence?.helm_charts as unknown[] | undefined)?.length ?? 0) > 0 },
    { name: 'Prometheus', present: Boolean(evidence?.prometheus) },
    { name: 'OpenTelemetry', present: Boolean(evidence?.otel) },
  ]
  return (
    <div className="space-y-1">
      {items.map((item) => <EvidenceRow key={item.name} name={item.name} present={item.present} />)}
    </div>
  )
}

