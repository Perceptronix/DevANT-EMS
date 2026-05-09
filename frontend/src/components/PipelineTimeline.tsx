import { useMemo } from 'react'
import { StatusDot, StatusColor } from '@/components/ui/StatusDot'

interface Props {
  snapshot: any | null
}

const STAGES = [
  { key: 'repository_ingestion', name: 'Project Scan' },
  { key: 'workflow_discovery', name: 'Workflow Check' },
  { key: 'deployment_analysis', name: 'Deployment Setup' },
  { key: 'observability_analysis', name: 'Monitoring Check' },
  { key: 'topology_inference', name: 'Service Connections' },
  { key: 'topology_propagation', name: 'Impact Analysis' },
  { key: 'regression_risk_analysis', name: 'Stability Check' },
  { key: 'operational_scoring', name: 'System Health' },
  { key: 'confidence_calibration', name: 'Reliability Score' },
  { key: 'final_operational_synthesis', name: 'Final Summary' },
]

function stateStatusColor(s?: string): StatusColor {
  if (!s || s === 'pending') return 'gray'
  if (s === 'running' || s === 'partial') return 'blue'
  if (s === 'completed') return 'green'
  return 'red'
}

export default function PipelineTimeline({ snapshot }: Props) {
  const items = useMemo(() => {
    const partial = snapshot?.partial || snapshot?.result_snapshot?.partial || {}
    return STAGES.map(({ key, name }) => {
      // support both snake_case and Title Case variants from backend just in case
      const originalTitleKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
      
      const entry = partial[key] || partial[originalTitleKey] || null
      const ts = entry?.last_event?.timestamp || entry?.last_event?.partial_result?.timestamp || null
      const status = entry?.state || (entry?.status ? String(entry.status).toLowerCase() : 'pending')
      return { name, status, ts }
    })
  }, [snapshot])

  return (
    <div className="space-y-2 text-sm">
      {items.map((it) => (
        <div key={it.name} className="flex items-center justify-between py-1">
          <div className="flex items-center gap-3">
            <StatusDot status={stateStatusColor(it.status)} animate={it.status === 'running' || it.status === 'partial'} />
            <span className="text-muted-foreground">{it.name}</span>
          </div>
          <div className="text-xs text-muted-foreground">
            {it.ts ? String(it.ts).slice(11, 19) : (it.status === 'pending' ? '-' : it.status)}
          </div>
        </div>
      ))}
    </div>
  )
}
