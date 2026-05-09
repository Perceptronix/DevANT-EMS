import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { StatusDot } from '@/components/ui/StatusDot'

interface Props {
  recurring?: boolean
  recurrenceCount?: number
  driftScore?: number
  lineageDepth?: number
  similarCount?: number
}

export default function TemporalMemoryCard({
  recurring,
  recurrenceCount,
  driftScore,
  lineageDepth,
  similarCount,
}: Props) {
  const [expanded, setExpanded] = useState(false)

  // Status is yellow if recurring, green if not, gray if unknown.
  const status = recurring === undefined ? 'gray' : recurring ? 'yellow' : 'green'

  return (
    <div className="group overflow-hidden">
      <div 
        className="flex items-center justify-between p-3 cursor-pointer hover:bg-muted/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <StatusDot status={status} />
          <span className="text-sm font-medium">Past System Activity</span>
        </div>

        <div className="flex items-center gap-4">
          <span className="text-xs text-muted-foreground">
            {recurring ? 'Recurring pattern' : recurring === false ? 'No strong recurrence' : ''}
          </span>
          <ChevronRight className={`h-4 w-4 text-muted-foreground transition-transform ${expanded ? 'rotate-90' : ''}`} />
        </div>
      </div>

      {expanded && (
        <div className="px-3 pb-3 pt-0 text-sm space-y-2 border-t border-border/50 mt-1">
          <div className="pt-2"></div>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-md bg-muted/20 p-2 text-xs">
              <div className="font-medium">Repeated Problems</div>
              <div className="text-muted-foreground mt-1">{typeof recurrenceCount === 'number' ? `${recurrenceCount} related incidents` : 'Unknown'}</div>
            </div>
            <div className="rounded-md bg-muted/20 p-2 text-xs">
              <div className="font-medium">Issue Patterns</div>
              <div className="text-muted-foreground mt-1">{typeof driftScore === 'number' ? `${Math.round(driftScore * 100)}% drift risk` : 'Unknown'}</div>
            </div>
            <div className="rounded-md bg-muted/20 p-2 text-xs">
              <div className="font-medium">Issue History Chain</div>
              <div className="text-muted-foreground mt-1">{typeof lineageDepth === 'number' ? `${lineageDepth} incidents in chain` : 'Unknown'}</div>
            </div>
            <div className="rounded-md bg-muted/20 p-2 text-xs">
              <div className="font-medium">Similar Past Issues</div>
              <div className="text-muted-foreground mt-1">{typeof similarCount === 'number' ? `${similarCount} similar incidents` : 'Unknown'}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
