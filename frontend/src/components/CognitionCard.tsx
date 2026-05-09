import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { CognitionLayer } from '@/models/cognitionLayers'

interface Props {
  id: string
  title: string
  layer?: CognitionLayer
  score?: number
  status?: string
  summary?: string
  onExpand?: () => void
}

export function CognitionCard({ id, title, layer, score, status, summary }: Props) {
  return (
    <Card className="transition-all" data-id={id} data-status={status}>
      <CardHeader className="flex items-center justify-between">
        <div>
          <CardTitle className="text-sm font-medium">{title}</CardTitle>
          {summary && <div className="text-xs text-muted-foreground">{summary}</div>}
        </div>
        <div className="flex items-center gap-2">
          {typeof score === 'number' && (
            <div className="text-xs text-muted-foreground">{Math.round(score * 100)}%</div>
          )}
          <Badge variant="outline">{(layer as any) ?? 'system'}</Badge>
        </div>
      </CardHeader>

      <CardContent>
        {/* Minimal content placeholder; details are behind expand */}
        <div className="text-xs text-muted-foreground">Tap to expand for details</div>
      </CardContent>
    </Card>
  )
}

export default CognitionCard
