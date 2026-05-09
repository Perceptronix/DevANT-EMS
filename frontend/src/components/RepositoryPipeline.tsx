import { useMemo, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { StatusDot, StatusColor } from '@/components/ui/StatusDot'
import PropagationCard from '@/components/PropagationCard'
import TemporalMemoryCard from '@/components/TemporalMemoryCard'

type StageState = 'pending' | 'running' | 'completed' | 'failed' | 'partial'

interface StageData {
  id: string
  name: string
  state?: StageState
  progress?: number // 0..1
  evidence?: Array<{ title: string; details?: string }>
  note?: string
}

interface Props {
  snapshot: any | null
}

interface PropagationMetrics {
  blastRadius?: number
  dominantService?: string
  criticalPath?: string
  riskDirection?: string
}

interface TemporalMemoryMetrics {
  recurring?: boolean
  recurrenceCount?: number
  driftScore?: number
  lineageDepth?: number
  similarCount?: number
}

const DEFAULT_STAGE_IDS = [
  'repository_ingestion',
  'workflow_discovery',
  'deployment_analysis',
  'observability_analysis',
  'topology_inference',
  'topology_propagation',
  'regression_risk_analysis',
  'operational_scoring',
  'confidence_calibration',
  'final_operational_synthesis',
]

const STAGE_NAME_MAP: Record<string, string> = {
  repository_ingestion: 'Project Scan',
  workflow_discovery: 'Workflow Check',
  deployment_analysis: 'Deployment Setup',
  observability_analysis: 'Monitoring Check',
  topology_inference: 'Service Connections',
  topology_propagation: 'Impact Analysis',
  regression_risk_analysis: 'Stability Check',
  operational_scoring: 'System Health',
  confidence_calibration: 'Reliability Score',
  final_operational_synthesis: 'Final Summary',
}

export function normalize(s: string) {
  if (!s) return s
  if (STAGE_NAME_MAP[s]) return STAGE_NAME_MAP[s]
  const step = s.replace(/[-_]+/g, ' ').replace(/([a-z0-9])([A-Z])/g, '$1 $2')
  return step
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(' ')
}

function stateStatusColor(s?: StageState): StatusColor {
  if (!s || s === 'pending') return 'gray'
  if (s === 'running' || s === 'partial') return 'blue'
  if (s === 'completed') return 'green'
  return 'red'
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  return undefined
}

function asString(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim()) return value
  return undefined
}

function extractPropagationMetrics(stage: StageData, snapshot: any): PropagationMetrics {
  const partial = snapshot?.partial ?? snapshot?.result_snapshot?.partial
  const raw = partial?.topology_propagation ?? partial?.topologyPropagation ?? {}
  const rawData = raw?.data ?? raw

  const stageData = stage.evidence && stage.evidence.length > 0 ? stage.evidence : undefined

  const blastRadius =
    asNumber(rawData?.blast_radius) ??
    asNumber(rawData?.propagation_result?.blast_radius) ??
    asNumber((rawData?.data as any)?.blast_radius)

  const dominantService =
    asString(rawData?.dominant_service) ??
    asString(rawData?.propagation_result?.dominant_service) ??
    asString((rawData?.data as any)?.dominant_service)

  const criticalPaths =
    rawData?.critical_paths ??
    rawData?.propagation_result?.critical_paths ??
    (rawData?.data as any)?.critical_paths

  let criticalPath: string | undefined
  if (Array.isArray(criticalPaths) && criticalPaths.length > 0) {
    const firstPath = criticalPaths[0]
    if (Array.isArray(firstPath)) {
      criticalPath = firstPath.filter(Boolean).join(' → ')
    } else if (typeof firstPath === 'string') {
      criticalPath = firstPath
    }
  }

  const upstreamRisk =
    asNumber(rawData?.upstream_risk) ??
    asNumber(rawData?.propagation_result?.upstream_risk) ??
    asNumber((rawData?.data as any)?.upstream_risk)
  const downstreamRisk =
    asNumber(rawData?.downstream_risk) ??
    asNumber(rawData?.propagation_result?.downstream_risk) ??
    asNumber((rawData?.data as any)?.downstream_risk)

  let riskDirection: string | undefined
  if (typeof upstreamRisk === 'number' && typeof downstreamRisk === 'number') {
    if (downstreamRisk > upstreamRisk) riskDirection = 'Downstream risk elevated'
    else if (upstreamRisk > downstreamRisk) riskDirection = 'Upstream risk elevated'
    else riskDirection = 'Balanced risk spread'
  }

  if (!criticalPath && stageData && stageData.length > 0) {
    const match = stageData.find((e) => e?.title?.toLowerCase().includes('critical path'))
    criticalPath = match?.details
  }

  return {
    blastRadius,
    dominantService,
    criticalPath,
    riskDirection,
  }
}

function extractTemporalMemoryMetrics(snapshot: any): TemporalMemoryMetrics {
  const evidence = snapshot?.result_snapshot?.evidence
  const temporal =
    evidence?.temporal_memory ??
    snapshot?.partial?.temporal_memory_analysis ??
    snapshot?.result_snapshot?.partial?.temporal_memory_analysis ??
    {}

  const recurring = temporal?.recurring_patterns ?? temporal?.recurring ?? {}
  const drift = temporal?.operational_drift ?? temporal?.drift ?? {}
  const similarity = temporal?.historical_similarity ?? temporal?.similarity ?? {}
  const lineage = temporal?.incident_lineage ?? temporal?.lineage ?? []

  return {
    recurring: Boolean(recurring?.is_recurring ?? recurring?.recurring),
    recurrenceCount: asNumber(recurring?.recurrence_count ?? recurring?.count),
    driftScore: asNumber(drift?.drift_score ?? drift?.score),
    lineageDepth: Array.isArray(lineage) ? lineage.length : asNumber(lineage?.depth),
    similarCount: asNumber(similarity?.similar_count ?? similarity?.count),
  }
}

export default function RepositoryPipeline({ snapshot }: Props) {
  const temporalMetrics = extractTemporalMemoryMetrics(snapshot)

  const pipeline: StageData[] = useMemo(() => {
    const data: StageData[] = []
    const partial = snapshot?.partial ?? snapshot?.result_snapshot?.partial

    // If backend supplies explicit array pipeline, use it
    if (partial?.pipeline && Array.isArray(partial.pipeline)) {
      for (const s of partial.pipeline) {
        data.push({
          id: s.id || s.name,
          name: normalize(s.name || s.id),
          state: s.state,
          progress: typeof s.progress === 'number' ? s.progress : undefined,
          evidence: s.evidence,
          note: s.note,
        })
      }
      // ensure all default stages present
      for (const id of DEFAULT_STAGE_IDS) {
        const name = normalize(id)
        if (!data.find((d) => d.id === id || d.name === name)) data.push({ id, name, state: 'pending' })
      }
      return data
    }

    // If partial is object keyed by step id/name, map onto DEFAULT_STAGES in order
    if (partial && typeof partial === 'object') {
      for (const id of DEFAULT_STAGE_IDS) {
        const name = normalize(id)
        let entry: any = undefined
        if (Object.prototype.hasOwnProperty.call(partial, id)) {
          entry = partial[id]
        } else if (Object.prototype.hasOwnProperty.call(partial, name)) {
          entry = partial[name]
        }

        if (entry) {
          // Convert evidence object to array format
          let evidenceArray: Array<{ title: string; details?: string }> | undefined = undefined
          const rawEvidence = entry.evidence || entry.data?.evidence
          if (rawEvidence) {
            if (Array.isArray(rawEvidence)) {
              evidenceArray = rawEvidence
            } else if (typeof rawEvidence === 'object') {
              // Convert dict to array: keys become titles, values become details
              evidenceArray = Object.entries(rawEvidence).map(([key, value]) => ({
                title: normalize(key),
                details: typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value),
              }))
            }
          }

          data.push({
            id,
            name,
            state: entry.state || (entry.status as StageState) || 'partial',
            progress: typeof entry.progress === 'number' ? entry.progress : undefined,
            evidence: evidenceArray,
            note: entry.note || entry.reasoning || entry.data?.note,
          })
        } else {
          data.push({ id, name, state: 'pending' })
        }
      }
      return data
    }

    // fallback: no partial info
    return DEFAULT_STAGE_IDS.map((id) => ({ id, name: normalize(id), state: 'pending' as StageState }))
  }, [snapshot])

  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium">Operational Pipeline</h2>

      <div className="space-y-2">
        {pipeline.map((stage) => (
          stage.id === 'topology_propagation' ? (
            <div key={stage.id} className="rounded-md border border-border bg-card">
              <PropagationCard
                status={stage.state}
                progress={stage.progress}
                {...extractPropagationMetrics(stage, snapshot)}
              />
            </div>
          ) : (
            <div key={stage.id} className="rounded-md border border-border bg-card group overflow-hidden">
              <div 
                className="flex items-center justify-between p-3 cursor-pointer hover:bg-muted/30 transition-colors"
                onClick={() => setExpanded((s) => ({ ...s, [stage.id]: !s[stage.id] }))}
              >
                <div className="flex items-center gap-3">
                  <StatusDot status={stateStatusColor(stage.state)} animate={stage.state === 'running' || stage.state === 'partial'} />
                  <span className="text-sm font-medium">{stage.name}</span>
                </div>

                <div className="flex items-center gap-4">
                  <span className="text-xs text-muted-foreground truncate max-w-[200px]">
                    {stage.note || (stage.progress ? `${Math.round((stage.progress ?? 0) * 100)}%` : '')}
                  </span>
                  <ChevronRight className={`h-4 w-4 text-muted-foreground transition-transform ${expanded[stage.id] ? 'rotate-90' : ''}`} />
                </div>
              </div>

              {expanded[stage.id] && (
                <div className="px-3 pb-3 pt-0 text-sm space-y-2 border-t border-border/50 mt-1">
                  <div className="pt-2"></div>
                  {stage.evidence && stage.evidence.length > 0 ? (
                    stage.evidence.map((e, i) => (
                      <div key={i} className="rounded-md bg-muted/20 p-2 text-xs">
                        <div className="font-medium">{e.title}</div>
                        {e.details && <div className="text-muted-foreground mt-1">{e.details}</div>}
                      </div>
                    ))
                  ) : (
                    <div className="text-xs text-muted-foreground italic">No evidence available.</div>
                  )}
                </div>
              )}
            </div>
          )
        ))}

        <div className="rounded-md border border-border bg-card">
          <TemporalMemoryCard {...temporalMetrics} />
        </div>
      </div>
    </section>
  )
}
