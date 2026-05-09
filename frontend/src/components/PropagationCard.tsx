import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { StatusDot, StatusColor } from '@/components/ui/StatusDot'

interface Props {
  status?: string
  progress?: number
  blastRadius?: number
  dominantService?: string
  criticalPath?: string
  riskDirection?: string
}

function stateStatusColor(s?: string): StatusColor {
  if (!s || s === 'pending') return 'gray'
  if (s === 'running' || s === 'partial') return 'blue'
  if (s === 'completed') return 'green'
  return 'red'
}

export default function PropagationCard({
  status,
  progress,
  blastRadius,
  dominantService,
  criticalPath,
  riskDirection,
}: Props) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="group overflow-hidden">
      <div 
        className="flex items-center justify-between p-3 cursor-pointer hover:bg-muted/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <StatusDot status={stateStatusColor(status)} animate={status === 'running' || status === 'partial'} />
          <span className="text-sm font-medium">Impact Analysis</span>
        </div>

        <div className="flex items-center gap-4">
          <span className="text-xs text-muted-foreground">
            {typeof progress === 'number' && progress > 0 ? `${Math.round(progress * 100)}%` : ''}
          </span>
          <ChevronRight className={`h-4 w-4 text-muted-foreground transition-transform ${expanded ? 'rotate-90' : ''}`} />
        </div>
      </div>

      {expanded && (
        <div className="px-3 pb-3 pt-0 text-sm space-y-2 border-t border-border/50 mt-1">
          <div className="pt-2"></div>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-md bg-muted/20 p-2 text-xs">
              <div className="font-medium">Affected Services</div>
              <div className="text-muted-foreground mt-1">{typeof blastRadius === 'number' ? `${blastRadius} downstream` : 'Unknown'}</div>
            </div>
            <div className="rounded-md bg-muted/20 p-2 text-xs">
              <div className="font-medium">Main Service</div>
              <div className="text-muted-foreground mt-1 break-all">{dominantService || 'Unknown'}</div>
            </div>
            <div className="rounded-md bg-muted/20 p-2 text-xs">
              <div className="font-medium">Spread Risk</div>
              <div className="text-muted-foreground mt-1 break-words">{criticalPath || 'Unknown'}</div>
            </div>
            <div className="rounded-md bg-muted/20 p-2 text-xs">
              <div className="font-medium">Issue Impact Direction</div>
              <div className="text-muted-foreground mt-1">{riskDirection || 'Unknown'}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
