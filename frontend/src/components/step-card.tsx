import { useState, useEffect } from 'react'
import Icons from '@/lib/icons'
import { ChevronDown, ChevronRight, ArrowRight } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'

interface StepCardProps {
  step: {
    id: string
    name: string
    status: 'pending' | 'running' | 'completed' | 'error'
    data?: Record<string, unknown>
    reasoning?: string
    duration_ms?: number
  }
  isActive: boolean
  autoExpand?: boolean  // Whether to auto-expand when running
  forceOpen?: boolean   // Force the card to stay open
  autoCollapse?: boolean // Whether to auto-collapse when completed
}

export function StepCard({ step, isActive, autoExpand = false, forceOpen = false, autoCollapse = false }: StepCardProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [wasAutoExpanded, setWasAutoExpanded] = useState(false)

  // Auto-expand when step starts running (if autoExpand is enabled)
  useEffect(() => {
    if (autoExpand && step.status === 'running' && step.data && !wasAutoExpanded) {
      setIsOpen(true)
      setWasAutoExpanded(true)
    }
  }, [autoExpand, step.status, step.data, wasAutoExpanded])

  // Auto-collapse when step completes (if autoCollapse is enabled and not forceOpen)
  useEffect(() => {
    if (autoCollapse && step.status === 'completed' && wasAutoExpanded && !forceOpen) {
      setIsOpen(false)
    }
  }, [autoCollapse, step.status, wasAutoExpanded, forceOpen])

  // Handle forceOpen (for the final step)
  useEffect(() => {
    if (forceOpen && step.data) {
      setIsOpen(true)
    }
  }, [forceOpen, step.data])

  // Reset wasAutoExpanded when pipeline restarts (step goes back to pending)
  useEffect(() => {
    if (step.status === 'pending') {
      setWasAutoExpanded(false)
      setIsOpen(false)
    }
  }, [step.status])

  const statusIcon = {
    pending: <Icons.Clock className="h-4 w-4 text-muted-foreground" />,
    running: <Icons.Loader2 className="h-4 w-4 text-primary animate-spin" />,
    completed: <Icons.Check className="h-4 w-4 text-green-500" />,
    error: <Icons.AlertCircle className="h-4 w-4 text-destructive" />,
  }

  const statusBadge = {
    pending: <Badge variant="outline">Pending</Badge>,
    running: <Badge variant="default">Running</Badge>,
    completed: <Badge variant="secondary">Completed</Badge>,
    error: <Badge variant="destructive">Error</Badge>,
  }

  return (
    <Card className={cn(
      "transition-all duration-300",
      isActive && "ring-2 ring-primary",
      step.status === 'running' && "animate-step-pulse"
    )}>
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {statusIcon[step.status]}
              <CardTitle className="text-base">{step.name}</CardTitle>
            </div>
            <div className="flex items-center gap-2">
              {step.duration_ms !== undefined && (
                <span className="text-xs text-muted-foreground">
                  {step.duration_ms}ms
                </span>
              )}
              {statusBadge[step.status]}
              {step.data && (
                <CollapsibleTrigger asChild>
                  <button className="p-1 hover:bg-accent rounded">
                    {isOpen ? (
                      <ChevronDown className="h-4 w-4" />
                    ) : (
                      <ChevronRight className="h-4 w-4" />
                    )}
                  </button>
                </CollapsibleTrigger>
              )}
            </div>
          </div>
        </CardHeader>

        <CollapsibleContent>
          <CardContent className="p-0">
            <div className="max-h-[50vh] overflow-y-auto p-6 pt-0">
              {step.data && (
                <div className="space-y-4">
                  {/* Step-specific content rendering */}
                  <StepDataRenderer stepId={step.id} data={step.data} />
                  
                  {/* Reasoning section */}
                  {step.reasoning && (
                    <div className="mt-4 pt-4 border-t border-border">
                      <div className="rounded-lg border border-purple-500/20 bg-gradient-to-br from-purple-500/5 to-blue-500/5 overflow-hidden">
                        {/* Header */}
                        <div className="flex items-center gap-2 px-3 py-2 bg-purple-500/10 border-b border-purple-500/20">
                          <SparklesIcon className="h-4 w-4 text-purple-400" />
                          <span className="text-xs font-medium text-purple-300">AI Reasoning</span>
                        </div>
                        {/* Content */}
                        <div className="p-3">
                          <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap">
                            {step.reasoning}
                          </p>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}

interface StepDataRendererProps {
  stepId: string
  data: Record<string, unknown>
}

function StepDataRenderer({ stepId, data }: StepDataRendererProps) {
  switch (stepId) {
    case 'raw-errors':
      return <RawErrorsData data={data} />
    case 'clustering':
      return <ClusteringData data={data} />
    case 'context-search':
      return <ContextSearchData data={data} />
    case 'analysis':
      return <AnalysisData data={data} />
    case 'alert-preview':
      return <AlertPreviewData data={data} />
    default:
      return <pre className="code-block text-xs">{JSON.stringify(data, null, 2)}</pre>
  }
}

function RawErrorsData({ data }: { data: Record<string, unknown> }) {
  const errors = (data.errors || []) as Array<{
    id: string
    level: string
    message: string
    module: string
    function: string
    org_name: string
    timestamp?: string
    line?: number
  }>

  const errorCount = errors.filter(e => e.level === 'ERROR').length
  const warningCount = errors.filter(e => e.level === 'WARNING').length
  const orgsAffected = (data.orgs_affected as string[]) || []

  // Generate fake timestamps for demo
  const getTimestamp = (idx: number) => {
    const now = new Date()
    now.setMinutes(now.getMinutes() - idx * 2)
    return now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  const levelColors: Record<string, string> = {
    ERROR: 'text-red-400',
    WARNING: 'text-yellow-400',
    INFO: 'text-blue-400',
    DEBUG: 'text-gray-400',
  }

  const levelBgColors: Record<string, string> = {
    ERROR: 'bg-red-500/20 border-red-500/30',
    WARNING: 'bg-yellow-500/20 border-yellow-500/30',
    INFO: 'bg-blue-500/20 border-blue-500/30',
    DEBUG: 'bg-gray-500/20 border-gray-500/30',
  }
  
  // Stagger class helper
  const getStaggerClass = (idx: number) => `stagger-${Math.min(idx + 1, 10)}`
  
  return (
    <div className="space-y-3">
      {/* Stats bar */}
      <div className="flex items-center gap-3 p-3 bg-muted/30 rounded-lg animate-fade-in">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            <span className="text-sm font-medium">{errorCount} errors</span>
          </div>
          {warningCount > 0 && (
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-yellow-500" />
              <span className="text-sm font-medium">{warningCount} warnings</span>
            </div>
          )}
          <div className="h-4 w-px bg-border" />
          <span className="text-sm text-muted-foreground">
            {orgsAffected.length} org{orgsAffected.length !== 1 ? 's' : ''} affected
          </span>
        </div>
        <div className="ml-auto text-xs text-muted-foreground">
          Last 5 minutes
        </div>
      </div>

      {/* Log viewer style container */}
      <div className="bg-[#0d1117] rounded-lg border border-[#30363d] overflow-hidden font-mono text-[12px] animate-fade-in stagger-1">
        {/* Header bar */}
        <div className="flex items-center gap-2 px-3 py-2 bg-[#161b22] border-b border-[#30363d] text-gray-400">
          <TerminalIcon className="h-3.5 w-3.5" />
          <span>Application Logs</span>
          <span className="ml-auto text-[10px]">{errors.length} entries</span>
        </div>

        {/* Log entries */}
        <div className="max-h-72 overflow-y-auto">
          {errors.slice(0, 8).map((error, idx) => (
            <div 
              key={error.id || idx} 
              className={cn(
                "flex items-start gap-3 px-3 py-2 border-b border-[#21262d] hover:bg-[#161b22] transition-colors",
                "animate-fade-in",
                getStaggerClass(idx + 2),
                idx === 0 && "bg-[#161b22]"
              )}
            >
              {/* Timestamp */}
              <span className="text-gray-500 flex-shrink-0 tabular-nums">
                {error.timestamp || getTimestamp(idx)}
              </span>

              {/* Level badge */}
              <span className={cn(
                "px-1.5 py-0.5 rounded text-[10px] font-semibold flex-shrink-0 border",
                levelBgColors[error.level] || levelBgColors.ERROR
              )}>
                <span className={levelColors[error.level] || levelColors.ERROR}>
                  {error.level}
                </span>
              </span>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-cyan-400">{error.module}</span>
                  <span className="text-gray-500">→</span>
                  <span className="text-purple-400">{error.function}</span>
                      {error.line && (
                    <>
                      <span className="text-gray-500">:</span>
                      <span className="text-accent">{error.line}</span>
                    </>
                  )}
                </div>
                <p className="text-gray-300 truncate">{error.message}</p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] px-1.5 py-0.5 bg-[#21262d] rounded text-gray-400">
                    org:{error.org_name}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        {errors.length > 8 && (
          <div className="px-3 py-2 bg-[#161b22] border-t border-[#30363d] text-center text-gray-500">
            + {errors.length - 8} more entries
          </div>
        )}
      </div>

      {/* Affected orgs breakdown */}
      {orgsAffected.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 bg-muted/30 border-b border-border">
            <div className="flex items-center gap-2">
              <BuildingIcon className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">Affected Organizations</span>
            </div>
            <span className="text-xs text-muted-foreground">{orgsAffected.length} total</span>
          </div>
          <div className="p-3">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {orgsAffected.slice(0, 6).map((org, idx) => {
                // Count errors for this org
                const orgErrorCount = errors.filter(e => e.org_name === org).length
                const isHighImpact = orgErrorCount >= 3
                
                return (
                  <div 
                    key={idx}
                    className={cn(
                      "flex items-center justify-between px-3 py-2 rounded-md border",
                      isHighImpact 
                        ? "bg-red-500/10 border-red-500/30" 
                        : "bg-muted/30 border-border"
                    )}
                  >
                    <span className={cn(
                      "text-sm font-medium truncate",
                      isHighImpact && "text-red-400"
                    )}>
                      {org}
                    </span>
                    <span className={cn(
                      "text-xs px-1.5 py-0.5 rounded-full ml-2 flex-shrink-0",
                      isHighImpact 
                        ? "bg-red-500/20 text-red-400" 
                        : "bg-muted text-muted-foreground"
                    )}>
                      {orgErrorCount}
                    </span>
                  </div>
                )
              })}
            </div>
            {orgsAffected.length > 6 && (
              <p className="text-xs text-muted-foreground text-center mt-3">
                + {orgsAffected.length - 6} more organizations
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// Building icon component
function BuildingIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="2" width="16" height="20" rx="2" ry="2" />
      <path d="M9 22v-4h6v4" />
      <path d="M8 6h.01" />
      <path d="M16 6h.01" />
      <path d="M12 6h.01" />
      <path d="M12 10h.01" />
      <path d="M12 14h.01" />
      <path d="M16 10h.01" />
      <path d="M16 14h.01" />
      <path d="M8 10h.01" />
      <path d="M8 14h.01" />
    </svg>
  )
}

// Terminal icon component
function TerminalIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="4 17 10 11 4 5" />
      <line x1="12" y1="19" x2="20" y2="19" />
    </svg>
  )
}

function ClusteringData({ data }: { data: Record<string, unknown> }) {
  const clusters = (data.clusters || []) as Array<{
    signature: string
    error_count: number
    affected_orgs: string[]
  }>

  // Parse reduction string like "15 errors → 3 clusters"
  const reductionText = data.reduction as string || ''
  const reductionMatch = reductionText.match(/(\d+)\s*errors?\s*→\s*(\d+)\s*clusters?/i)
  const originalCount = reductionMatch ? parseInt(reductionMatch[1]) : clusters.reduce((sum, c) => sum + c.error_count, 0)
  const clusterCount = reductionMatch ? parseInt(reductionMatch[2]) : clusters.length
  const reductionPercent = originalCount > 0 ? Math.round((1 - clusterCount / originalCount) * 100) : 0

  // Find max error count for relative sizing
  const maxErrors = Math.max(...clusters.map(c => c.error_count), 1)

  // Color palette for clusters
  const clusterColors = [
    { bg: 'bg-blue-500/20', border: 'border-blue-500/40', text: 'text-blue-400', bar: 'bg-blue-500' },
    { bg: 'bg-purple-500/20', border: 'border-purple-500/40', text: 'text-purple-400', bar: 'bg-purple-500' },
    { bg: 'bg-emerald-500/20', border: 'border-emerald-500/40', text: 'text-emerald-400', bar: 'bg-emerald-500' },
    { bg: 'bg-accent-soft', border: 'border-accent-soft', text: 'text-accent', bar: 'bg-accent' },
    { bg: 'bg-pink-500/20', border: 'border-pink-500/40', text: 'text-pink-400', bar: 'bg-pink-500' },
  ]
  
  // Stagger class helper
  const getStaggerClass = (idx: number) => `stagger-${Math.min(idx + 1, 10)}`
  
  return (
    <div className="space-y-4">
      {/* Reduction visualization */}
      <div className="p-4 bg-gradient-to-r from-muted/50 to-muted/20 rounded-lg border border-border animate-fade-in">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            {/* Before */}
            <div className="text-center">
              <div className="text-2xl font-bold">{originalCount}</div>
              <div className="text-xs text-muted-foreground">raw errors</div>
            </div>
            
            {/* Arrow */}
            <div className="flex items-center gap-2 px-4">
              <ArrowRight className="h-5 w-5 text-muted-foreground" />
            </div>
            
            {/* After */}
            <div className="text-center">
              <div className="text-2xl font-bold text-primary">{clusterCount}</div>
              <div className="text-xs text-muted-foreground">clusters</div>
            </div>
          </div>

          {/* Reduction percentage */}
          <div className="flex items-center gap-2 px-3 py-1.5 bg-emerald-500/10 rounded-full border border-emerald-500/30">
            <TrendingDownIcon className="h-4 w-4 text-emerald-500" />
            <span className="text-sm font-medium text-emerald-500">{reductionPercent}% reduction</span>
          </div>
        </div>
      </div>

      {/* Clusters list */}
      <div className="space-y-3 animate-fade-in stagger-1">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="font-medium">Identified Clusters</span>
          <span className="text-xs px-1.5 py-0.5 bg-muted rounded">{clusters.length}</span>
        </div>

        {clusters.map((cluster, idx) => {
          const colors = clusterColors[idx % clusterColors.length]
          const barWidth = (cluster.error_count / maxErrors) * 100

          return (
            <div 
              key={idx} 
              className={cn(
                "rounded-lg border overflow-hidden animate-fade-in",
                getStaggerClass(idx + 2),
                colors.border,
                colors.bg
              )}
            >
              {/* Cluster header */}
              <div className="p-3">
                <div className="flex items-start gap-3">
                  {/* Cluster number badge */}
                  <div className={cn(
                    "w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0",
                    colors.bar,
                    "text-white"
                  )}>
                    {idx + 1}
                  </div>

                  <div className="flex-1 min-w-0">
                    {/* Signature */}
                    <p className="text-sm font-medium mb-2 leading-snug">{cluster.signature}</p>
                    
                    {/* Stats row */}
                    <div className="flex items-center gap-4">
                      {/* Error count with bar */}
                      <div className="flex items-center gap-2 flex-1 max-w-[200px]">
                        <span className="text-xs text-muted-foreground whitespace-nowrap">
                          {cluster.error_count} error{cluster.error_count !== 1 ? 's' : ''}
                        </span>
                        <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                          <div 
                            className={cn("h-full rounded-full transition-all", colors.bar)}
                            style={{ width: `${barWidth}%` }}
                          />
                        </div>
                      </div>

                      {/* Orgs affected */}
                      <div className="flex items-center gap-1.5">
                        <BuildingIcon className="h-3 w-3 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">
                          {cluster.affected_orgs.length} org{cluster.affected_orgs.length !== 1 ? 's' : ''}
                        </span>
                      </div>
                    </div>

                    {/* Affected orgs chips */}
                    {cluster.affected_orgs.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {cluster.affected_orgs.slice(0, 4).map((org, orgIdx) => (
                          <span 
                            key={orgIdx}
                            className="text-[10px] px-1.5 py-0.5 bg-background/50 rounded text-muted-foreground"
                          >
                            {org}
                          </span>
                        ))}
                        {cluster.affected_orgs.length > 4 && (
                          <span className="text-[10px] px-1.5 py-0.5 text-muted-foreground">
                            +{cluster.affected_orgs.length - 4}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// Cluster icon component

// Trending down icon component
function TrendingDownIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 18 13.5 8.5 8.5 13.5 1 6" />
      <polyline points="17 18 23 18 23 12" />
    </svg>
  )
}

// Sparkles icon component
function SparklesIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3l1.912 5.813a2 2 0 001.275 1.275L21 12l-5.813 1.912a2 2 0 00-1.275 1.275L12 21l-1.912-5.813a2 2 0 00-1.275-1.275L3 12l5.813-1.912a2 2 0 001.275-1.275L12 3z" />
      <path d="M5 3v4" />
      <path d="M3 5h4" />
      <path d="M19 17v4" />
      <path d="M17 19h4" />
    </svg>
  )
}

function ContextSearchData({ data }: { data: Record<string, unknown> }) {
  const results = (data.results || []) as Array<{
    cluster_signature: string
    context: {
      code_snippets?: Array<{ title: string; content: string; source: string }>
      related_tickets?: Array<{ title: string; content: string }>
      documentation?: Array<{ title: string; content: string; source: string }>
      is_mock?: boolean
    }
  }>

  const isMock = results[0]?.context?.is_mock
  
  // Count total context items found
  const totalCode = results.reduce((sum, r) => sum + (r.context.code_snippets?.length || 0), 0)
  const totalTickets = results.reduce((sum, r) => sum + (r.context.related_tickets?.length || 0), 0)
  const totalDocs = results.reduce((sum, r) => sum + (r.context.documentation?.length || 0), 0)
  
  // Stagger class helper
  const getStaggerClass = (idx: number) => `stagger-${Math.min(idx + 1, 10)}`
  
  return (
    <div className="space-y-4">
      {/* Search summary header */}
      <div className="p-4 bg-gradient-to-r from-cyan-500/10 to-blue-500/10 rounded-lg border border-cyan-500/20 animate-fade-in">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <SearchIcon className="h-5 w-5 text-cyan-400" />
            <span className="font-medium">Context Search via</span>
            <div className="flex items-center gap-1.5 px-2 py-0.5 bg-background/50 rounded-md border border-cyan-500/30">
              <AirweaveIcon className="h-4 w-4 text-cyan-400" />
              <span className="font-medium text-cyan-400">Airweave</span>
            </div>
          </div>
          {isMock && (
            <span className="text-xs px-2 py-1 bg-yellow-500/20 text-yellow-400 rounded-full border border-yellow-500/30">
              Demo Data
            </span>
          )}
        </div>
        
        {/* Sources searched */}
        <div className="flex flex-wrap gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-background/50 rounded-md border border-border animate-fade-in stagger-1">
            <CodeIcon className="h-4 w-4 text-emerald-400" />
            <span className="text-sm">Code</span>
            <span className="text-xs px-1.5 py-0.5 bg-emerald-500/20 text-emerald-400 rounded">
              {totalCode} found
            </span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 bg-background/50 rounded-md border border-border animate-fade-in stagger-2">
            <LinearIcon className="h-4 w-4 text-purple-400" />
            <span className="text-sm">Tickets</span>
            <span className="text-xs px-1.5 py-0.5 bg-purple-500/20 text-purple-400 rounded">
              {totalTickets} found
            </span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 bg-background/50 rounded-md border border-border animate-fade-in stagger-3">
            <SlackIcon className="h-4 w-4 text-[#E01E5A]" />
            <span className="text-sm">Slack</span>
            <span className="text-xs px-1.5 py-0.5 bg-pink-500/20 text-pink-400 rounded">
              {totalDocs} found
            </span>
          </div>
        </div>
      </div>

      {/* Results per cluster */}
      {results.map((result, idx) => (
        <div key={idx} className={cn("border border-border rounded-lg overflow-hidden animate-fade-in", getStaggerClass(idx + 4))}>
          {/* Cluster header */}
          <div className="px-4 py-3 bg-muted/30 border-b border-border">
            <div className="flex items-center gap-2">
              <div className="w-5 h-5 rounded-full bg-primary/20 flex items-center justify-center">
                <span className="text-xs font-bold text-primary">{idx + 1}</span>
              </div>
              <h4 className="text-sm font-medium flex-1">{result.cluster_signature}</h4>
            </div>
          </div>

          <div className="p-4 space-y-4">
            {/* Code snippets */}
            {result.context.code_snippets && result.context.code_snippets.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <CodeIcon className="h-3.5 w-3.5 text-emerald-400" />
                  <span className="font-medium uppercase tracking-wide">Related Code</span>
                </div>
                
                {result.context.code_snippets.map((snippet, sIdx) => (
                  <div key={sIdx} className="rounded-lg border border-[#30363d] overflow-hidden bg-[#0d1117]">
                    {/* File header */}
                    <div className="flex items-center gap-2 px-3 py-2 bg-[#161b22] border-b border-[#30363d]">
                      <FileCodeIcon className="h-4 w-4 text-gray-400" />
                      <span className="text-xs font-mono text-gray-300">{snippet.title}</span>
                      <span className="ml-auto text-[10px] px-1.5 py-0.5 bg-emerald-500/20 text-emerald-400 rounded">
                        {snippet.source}
                      </span>
                    </div>
                    {/* Code content */}
                    <pre className="p-3 text-xs font-mono text-gray-300 overflow-x-auto leading-relaxed">
                      {snippet.content.slice(0, 400)}
                      {snippet.content.length > 400 && (
                        <span className="text-gray-500">... more</span>
                      )}
                    </pre>
                  </div>
                ))}
              </div>
            )}

            {/* Related tickets */}
            {result.context.related_tickets && result.context.related_tickets.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <LinearIcon className="h-3.5 w-3.5 text-purple-400" />
                  <span className="font-medium uppercase tracking-wide">Related Tickets</span>
                </div>
                
                {result.context.related_tickets.map((ticket, tIdx) => (
                  <div key={tIdx} className="rounded-lg border border-purple-500/20 bg-purple-500/5 overflow-hidden">
                    <div className="p-3">
                      <div className="flex items-center gap-2 mb-2">
                        <LinearIcon className="h-4 w-4 text-purple-400" />
                        <span className="text-xs text-purple-400 font-mono">
                          ENG-{Math.floor(Math.random() * 9000) + 1000}
                        </span>
                        <span className="text-xs px-1.5 py-0.5 bg-green-500/20 text-green-400 rounded">
                          Resolved
                        </span>
                      </div>
                      <p className="text-sm font-medium mb-1">{ticket.title}</p>
                      <p className="text-xs text-muted-foreground line-clamp-2">{ticket.content}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Slack Threads */}
            {result.context.documentation && result.context.documentation.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <SlackIcon className="h-3.5 w-3.5 text-[#E01E5A]" />
                  <span className="font-medium uppercase tracking-wide">Slack Threads</span>
                </div>
                
                {result.context.documentation.map((doc, dIdx) => (
                  <div key={dIdx} className="rounded-lg border border-[#E01E5A]/20 bg-[#E01E5A]/5 overflow-hidden">
                    <div className="px-3 py-2 bg-[#1a1d21] border-b border-[#E01E5A]/20">
                      <div className="flex items-center gap-2">
                        <SlackIcon className="h-4 w-4 text-[#E01E5A]" />
                        <span className="text-sm font-medium text-white">{doc.title}</span>
                      </div>
                    </div>
                    <div className="p-3 bg-[#1a1d21]/50">
                      <p className="text-xs text-gray-300 leading-relaxed">{doc.content}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Empty state */}
            {!result.context.code_snippets?.length && 
             !result.context.related_tickets?.length && 
             !result.context.documentation?.length && (
              <p className="text-sm text-muted-foreground text-center py-4">
                No additional context found for this cluster
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// Search icon component
function SearchIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  )
}

// Code icon component
function CodeIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  )
}

// File code icon component
function FileCodeIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
      <polyline points="14 2 14 8 20 8" />
      <path d="m10 13-2 2 2 2" />
      <path d="m14 17 2-2-2-2" />
    </svg>
  )
}


function AnalysisData({ data }: { data: Record<string, unknown> }) {
  const analyses = (data.analyses || []) as Array<{
    signature: string
    severity: string
    root_cause: string
    impact: string
    suggested_action: string
    affected_orgs: string[]
    status?: string
  }>

  // Count severities
  const severityCounts = analyses.reduce((acc, a) => {
    acc[a.severity] = (acc[a.severity] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  const severityConfig: Record<string, { bg: string; border: string; text: string; icon: string; label: string }> = {
    S1: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-500', icon: '', label: 'Critical' },
    S2: { bg: 'bg-accent-soft', border: 'border-accent-soft', text: 'text-accent', icon: '', label: 'High' },
    S3: { bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', text: 'text-yellow-500', icon: '', label: 'Medium' },
    S4: { bg: 'bg-blue-500/10', border: 'border-blue-500/30', text: 'text-blue-500', icon: '', label: 'Low' },
  }
  
  // Stagger class helper
  const getStaggerClass = (idx: number) => `stagger-${Math.min(idx + 1, 10)}`
  
  return (
    <div className="space-y-4">
      {/* Severity summary */}
      <div className="p-4 bg-accent-gradient rounded-lg border border-accent-soft animate-fade-in">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <ShieldAlertIcon className="h-5 w-5 text-accent" />
            <span className="font-medium">Severity Analysis</span>
          </div>
          <span className="text-sm text-muted-foreground">{analyses.length} issue{analyses.length !== 1 ? 's' : ''} analyzed</span>
        </div>

        {/* Severity distribution */}
        <div className="flex gap-3">
          {(['S1', 'S2', 'S3', 'S4'] as const).map((sev, sevIdx) => {
            const count = severityCounts[sev] || 0
            const config = severityConfig[sev]
            return (
              <div 
                key={sev}
                className={cn(
                  "flex items-center gap-2 px-3 py-1.5 rounded-md border animate-fade-in",
                  getStaggerClass(sevIdx + 1),
                  count > 0 ? `${config.bg} ${config.border}` : "bg-muted/30 border-border opacity-50"
                )}
              >
                <span>{config.icon}</span>
                <span className={cn("text-sm font-medium", count > 0 ? config.text : "text-muted-foreground")}>
                  {sev}
                </span>
                <span className={cn(
                  "text-xs px-1.5 py-0.5 rounded-full",
                  count > 0 ? `${config.bg} ${config.text}` : "bg-muted text-muted-foreground"
                )}>
                  {count}
                </span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Individual analyses */}
      {analyses.map((analysis, idx) => {
        const config = severityConfig[analysis.severity] || severityConfig.S4
        
        return (
          <div 
            key={idx} 
            className={cn(
              "rounded-lg border overflow-hidden animate-fade-in",
              getStaggerClass(idx + 5),
              config.border,
              config.bg
            )}
          >
            {/* Header */}
            <div className="px-4 py-3 border-b border-inherit bg-background/50">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <div className={cn(
                    "w-8 h-8 rounded-lg flex items-center justify-center text-lg flex-shrink-0",
                    config.bg, config.border, "border"
                  )}>
                    {config.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <h4 className="text-sm font-medium leading-tight mb-1">{analysis.signature}</h4>
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        "text-xs px-2 py-0.5 rounded-full font-medium",
                        config.bg, config.text, config.border, "border"
                      )}>
                        {analysis.severity} - {config.label}
                      </span>
                      {analysis.status && (
                        <span className={cn(
                          "text-xs px-2 py-0.5 rounded-full",
                          analysis.status === 'NEW' && "bg-green-500/20 text-green-400 border border-green-500/30",
                          analysis.status === 'REGRESSION' && "bg-red-500/20 text-red-400 border border-red-500/30",
                          analysis.status === 'ONGOING' && "bg-blue-500/20 text-blue-400 border border-blue-500/30"
                        )}>
                          {analysis.status}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Content */}
            <div className="p-4 space-y-4">
              {/* Root Cause */}
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-lg bg-red-500/10 border border-red-500/20 flex items-center justify-center flex-shrink-0">
                  <TargetIcon className="h-4 w-4 text-red-400" />
                </div>
                <div className="flex-1">
                  <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Root Cause</div>
                  <p className="text-sm">{analysis.root_cause}</p>
                </div>
              </div>

              {/* Impact */}
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-lg bg-accent-soft border border-accent-soft flex items-center justify-center flex-shrink-0">
                  <ZapIcon className="h-4 w-4 text-accent" />
                </div>
                <div className="flex-1">
                  <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Impact</div>
                  <p className="text-sm">{analysis.impact}</p>
                </div>
              </div>

              {/* Suggested Action */}
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center flex-shrink-0">
                  <LightbulbIcon className="h-4 w-4 text-emerald-400" />
                </div>
                <div className="flex-1">
                  <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Suggested Action</div>
                  <p className="text-sm">{analysis.suggested_action}</p>
                </div>
              </div>

              {/* Affected Orgs */}
              {analysis.affected_orgs && analysis.affected_orgs.length > 0 && (
                <div className="pt-3 border-t border-inherit">
                  <div className="flex items-center gap-2 mb-2">
                    <BuildingIcon className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Affected Organizations ({analysis.affected_orgs.length})
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {analysis.affected_orgs.slice(0, 5).map((org, orgIdx) => (
                      <span 
                        key={orgIdx}
                        className="text-xs px-2 py-1 bg-background/50 rounded border border-border"
                      >
                        {org}
                      </span>
                    ))}
                    {analysis.affected_orgs.length > 5 && (
                      <span className="text-xs px-2 py-1 text-muted-foreground">
                        +{analysis.affected_orgs.length - 5} more
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// Shield alert icon component
function ShieldAlertIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <path d="M12 8v4" />
      <path d="M12 16h.01" />
    </svg>
  )
}

// Target icon component
function TargetIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="6" />
      <circle cx="12" cy="12" r="2" />
    </svg>
  )
}

// Zap icon component
function ZapIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  )
}

// Lightbulb icon component
function LightbulbIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5" />
      <path d="M9 18h6" />
      <path d="M10 22h4" />
    </svg>
  )
}

function AlertPreviewData({ data }: { data: Record<string, unknown> }) {
  const alerts = (data.alerts || []) as Array<{
    title: string
    severity: string
    description: string
    affected_orgs: string[]
    slack_preview: { blocks: Array<{ type: string; text: string }> }
    issue_preview: { title: string; description: string; labels: string[] }
  }>



  const priorityColors: Record<string, string> = {
    S1: 'bg-red-500',
    S2: 'bg-accent',
    S3: 'bg-yellow-500',
    S4: 'bg-blue-500',
  }

  // Stagger class helper
  const getStaggerClass = (idx: number) => `stagger-${Math.min(idx + 1, 10)}`
  
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground animate-fade-in">
        {data.total_alerts as number} alert(s) would be created
      </p>
      
      {alerts.map((alert, idx) => (
        <div key={idx} className={cn("space-y-4 animate-fade-in", getStaggerClass(idx + 1))}>
          {/* Alert Summary */}
          <div className="flex items-center gap-2">
            <Badge variant={alert.severity.toLowerCase() as 's1' | 's2' | 's3' | 's4'}>
              {alert.severity}
            </Badge>
            <span className="text-sm font-medium">{alert.title}</span>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            {/* Slack Preview - Realistic */}
            <div>
              <h5 className="text-xs font-mono uppercase text-muted-foreground mb-2 flex items-center gap-2">
                <SlackIcon className="h-4 w-4" />
                Slack Message
              </h5>
              <div className="bg-[#1a1d21] rounded-lg overflow-hidden text-[13px] font-[Lato,sans-serif] min-h-[200px]">
                {/* Slack message header */}
                <div className="flex items-start gap-2 p-3 pb-0">
                  <div className="w-9 h-9 rounded bg-gradient-to-br from-indigo-500 to-cyan-500 flex items-center justify-center text-lg flex-shrink-0">
                    🤖
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-white">Error Monitoring Agent</span>
                      <span className="text-[11px] text-gray-500">APP</span>
                      <span className="text-[11px] text-gray-500">12:34 PM</span>
                    </div>
                  </div>
                </div>

                {/* Slack message content */}
                <div className="px-3 pb-3 pl-14">
                  {/* Header block */}
                  <div className="text-white font-bold text-[15px] mb-2">
                    <Icons.AlertTriangle className="inline-block h-4 w-4 mr-2 text-accent" />
                    {alert.severity}: {alert.title.slice(0, 50)}
                  </div>
                  
                  {/* Section with colored border */}
                  <div className="border-l-4 border-l-[#e01e5a] pl-3 py-1 mb-3">
                    <div className="text-gray-300 text-[13px] leading-relaxed">
                      <span className="font-semibold text-white">Root Cause:</span> {alert.description.slice(0, 100)}...
                    </div>
                  </div>

                  {/* Fields */}
                  <div className="grid grid-cols-2 gap-2 mb-3 text-[12px]">
                    <div>
                      <div className="text-gray-500">Severity</div>
                      <div className="text-white">{alert.severity}</div>
                    </div>
                    <div>
                      <div className="text-gray-500">Affected</div>
                      <div className="text-white">{alert.affected_orgs?.length || 0} orgs</div>
                    </div>
                  </div>

                  {/* Context */}
                  <div className="text-gray-500 text-[11px] mb-3">
                    Orgs: {alert.affected_orgs?.slice(0, 3).join(', ')}
                  </div>

                  {/* Buttons */}
                  <div className="flex gap-2">
                    <button className="px-3 py-1.5 bg-[#2c2d30] text-white text-[12px] rounded border border-gray-600 hover:bg-[#3c3d40]">
                      Mute 1h
                    </button>
                    <button className="px-3 py-1.5 bg-[#2c2d30] text-white text-[12px] rounded border border-gray-600 hover:bg-[#3c3d40]">
                      Mute 8h
                    </button>
                    <button className="px-3 py-1.5 bg-[#2c2d30] text-white text-[12px] rounded border border-gray-600 hover:bg-[#3c3d40]">
                      Mute 24h
                    </button>
                  </div>
                </div>
              </div>
            </div>
            
            {/* Linear Preview - Realistic */}
            <div>
              <h5 className="text-xs font-mono uppercase text-muted-foreground mb-2 flex items-center gap-2">
                <LinearIcon className="h-4 w-4" />
                Linear Issue
              </h5>
              <div className="bg-white dark:bg-[#1f2023] rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden text-[13px] min-h-[200px]">
                {/* Linear issue header */}
                <div className="p-4 border-b border-gray-100 dark:border-gray-700">
                  <div className="flex items-center gap-2 mb-2">
                    {/* Priority indicator */}
                    <div className={cn("w-3 h-3 rounded-sm", priorityColors[alert.severity])} />
                    {/* Issue ID */}
                    <span className="text-gray-500 dark:text-gray-400 text-[12px] font-mono">
                      ENG-{Math.floor(Math.random() * 9000) + 1000}
                    </span>
                    {/* Status */}
                    <span className="px-2 py-0.5 bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 text-[11px] rounded-full">
                      Triage
                    </span>
                  </div>
                  <h3 className="font-semibold text-gray-900 dark:text-white text-[14px] leading-tight">
                    [{alert.severity}] {alert.title.slice(0, 60)}
                  </h3>
                </div>

                {/* Linear issue body */}
                <div className="p-4">
                  <p className="text-gray-600 dark:text-gray-300 text-[13px] leading-relaxed mb-3 line-clamp-3">
                    {alert.description}
                  </p>

                  {/* Labels */}
                  <div className="flex flex-wrap gap-1.5 mb-3">
                    <span className="px-2 py-0.5 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 text-[11px] rounded">
                      bug
                    </span>
                    <span className="px-2 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400 text-[11px] rounded">
                      monitoring
                    </span>
                    <span className={cn(
                      "px-2 py-0.5 text-[11px] rounded",
                      alert.severity === 'S1' && "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400",
                      alert.severity === 'S2' && "bg-accent-soft dark:bg-accent-soft text-accent dark:text-accent",
                      alert.severity === 'S3' && "bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400",
                      alert.severity === 'S4' && "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400",
                    )}>
                      {alert.severity.toLowerCase()}
                    </span>
                  </div>

                  {/* Meta */}
                  <div className="flex items-center gap-4 text-[11px] text-gray-500 dark:text-gray-400">
                    <span>Created just now</span>
                    <span>•</span>
                    <span>No assignee</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          
          {idx < alerts.length - 1 && <div className="border-b border-border" />}
        </div>
      ))}
    </div>
  )
}

// Slack icon component
function SlackIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zm1.271 0a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zm0 1.271a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zm10.124 2.521a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.52 2.521h-2.522V8.834zm-1.268 0a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zm-2.523 10.124a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.52v-2.522h2.52zm0-1.268a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/>
    </svg>
  )
}

// Linear icon component  
function LinearIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M3.03509 12.9431C3.24245 14.9227 4.10472 16.8468 5.62188 18.364C7.13904 19.8811 9.0631 20.7434 11.0428 20.9508L3.03509 12.9431Z"/>
      <path d="M3 11.4938L12.4921 20.9858C13.2976 20.9407 14.0981 20.7879 14.8704 20.5273L3.4585 9.11548C3.19793 9.88771 3.0451 10.6883 3 11.4938Z"/>
      <path d="M3.86722 8.10999L15.8758 20.1186C16.4988 19.8201 17.0946 19.4458 17.6493 18.9956L4.99021 6.33659C4.54006 6.89125 4.16573 7.487 3.86722 8.10999Z"/>
      <path d="M5.66301 5.59517C9.18091 2.12137 14.8488 2.135 18.3498 5.63604C21.8508 9.13708 21.8645 14.8049 18.3907 18.3228L5.66301 5.59517Z"/>
    </svg>
  )
}

// Airweave icon component
function AirweaveIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 143 143" fill="currentColor">
      <path d="M89.3854 128.578C79.4165 123.044 66.2502 114.852 60.0707 107.348L59.5432 106.724C58.2836 105.206 56.981 103.72 55.6676 102.299C51.4152 97.6699 46.8614 93.5036 42.146 89.9079C40.2405 88.4546 38.2704 87.055 36.3111 85.7847C35.2991 85.128 34.3302 84.5251 33.4151 83.9761C31.1221 82.6088 28.3338 82.2321 25.7716 82.9534C23.3385 83.6424 21.39 85.2464 20.2596 87.4534C18.0634 91.7381 19.5814 97.0347 23.7046 99.5108C27.0204 101.492 30.2608 103.817 33.3398 106.422C33.7381 106.756 33.8996 107.284 33.7596 107.768C32.6292 111.891 31.4989 118.663 31.0682 121.376C30.1424 127.135 32.9737 132.787 38.0982 135.457L38.2812 135.554C40.5204 136.706 43.1472 136.652 45.3219 135.403C47.4858 134.165 48.853 131.937 48.9822 129.439C49.036 128.363 49.1006 127.286 49.176 126.296C49.219 125.768 49.542 125.337 50.0264 125.165C50.1772 125.111 50.3494 125.079 50.5001 125.079C50.8554 125.079 51.1784 125.219 51.4475 125.488C55.743 129.891 60.3829 133.875 65.2167 137.33C69.8674 140.657 75.3686 142.412 81.139 142.412C83.2383 142.412 85.3376 142.175 87.3938 141.701L87.6199 141.647C90.4943 140.98 92.529 138.73 92.9488 135.791C93.3687 132.852 91.9476 130.02 89.3747 128.589H89.3639L89.3854 128.578Z"/>
      <path d="M142.051 57.8805L142.029 57.7621C141.545 55.2968 139.618 53.4128 137.098 52.9606C134.612 52.5192 132.254 53.5635 130.984 55.6951L130.908 55.8135C126.204 63.8662 119.561 71.3159 111.153 78.0014C108.946 79.7562 106.793 81.6078 104.726 83.5134C103.144 84.9775 100.765 85.2359 98.9452 84.127C97.1474 83.0397 95.3495 81.8447 93.6055 80.5744C89.8268 77.8291 86.1772 74.6533 82.7753 71.1329C80.9989 69.3028 79.298 67.3973 77.6939 65.438C75.5408 62.8219 73.2477 60.2597 70.8685 57.8374C65.8195 52.6915 56.1089 45.6185 53.2453 43.5838C52.8792 43.3362 52.6639 42.9486 52.5993 42.5073C52.5455 42.0659 52.6639 41.6567 52.9546 41.3122C54.774 39.1376 56.4965 36.8876 58.0683 34.6268C59.7369 32.2369 60.286 29.3086 59.5862 26.5957C58.908 23.9581 57.1424 21.8158 54.634 20.5885C50.4139 18.5 45.3972 19.8026 42.7273 23.6351C40.3373 27.0694 37.5167 30.439 34.3732 33.6364C34.0718 33.9378 33.6304 34.0455 33.2213 33.8948C30.0239 32.8505 26.7296 32 23.4461 31.3648C23.2093 31.3218 22.854 31.2572 22.4126 31.2034C15.9102 30.2345 9.61233 33.4857 6.71639 39.2775L6.6195 39.4606C5.68289 41.3338 5.76902 43.5407 6.82405 45.3709C7.90061 47.2226 9.82765 48.4068 11.9592 48.5252C12.9604 48.579 13.9401 48.6436 14.8659 48.7082C15.2966 48.7405 15.6411 48.9881 15.8025 49.3972C15.9533 49.8171 15.8671 50.2477 15.5657 50.5599C11.647 54.5862 8.10515 58.9032 5.0262 63.3925C0.644601 69.7872 -0.981008 77.9153 0.580002 85.688L0.601538 85.8064C1.20441 88.7777 3.55131 90.9093 6.57644 91.2323C9.48315 91.5445 12.1099 90.0266 13.2619 87.3782L13.3265 87.2167C18.1925 75.5683 26.2559 65.2226 37.2907 56.4594C37.8182 56.0503 38.5072 55.9858 39.067 56.298C44.8373 59.4738 50.3601 63.6078 55.4738 68.5923C56.0982 69.1951 56.1089 70.2071 55.5168 70.8315C52.9761 73.5122 50.5862 76.3112 48.4115 79.1749C46.7106 81.4141 47.0335 84.6007 49.1221 86.4416L52.8254 89.7036L52.7824 89.7467C53.3637 90.2634 53.945 90.7802 54.5264 91.2969L55.3123 91.8998C56.4319 92.8902 57.8529 93.3423 59.3386 93.1916C60.8027 93.0409 62.17 92.2658 63.0635 91.0816C64.6353 88.9931 66.3578 86.9584 68.1556 85.0098C68.457 84.676 68.8661 84.5038 69.3075 84.4931C69.7705 84.4931 70.1257 84.6437 70.4164 84.9344C75.3147 89.7682 80.6114 94.0744 86.1772 97.7024C88.3626 99.1234 88.9978 101.966 87.6306 104.183C86.4248 106.153 85.2729 108.199 84.2179 110.244C83.0014 112.624 82.7968 115.444 83.6688 117.963C84.4978 120.385 86.2095 122.291 88.481 123.346C89.7514 123.938 91.0971 124.24 92.4859 124.24C96.0062 124.24 99.182 122.302 100.786 119.158C102.229 116.316 103.919 113.506 105.781 110.836C106.869 109.265 108.86 108.543 110.755 109.028C114.76 110.061 120.143 111.127 123.954 111.848C127.808 112.57 131.619 110.729 133.46 107.284L133.643 106.939C135.021 104.334 135.031 101.212 133.664 98.5959C132.286 95.9584 129.681 94.1713 126.71 93.8268C125.978 93.7407 125.278 93.6546 124.61 93.5684C124.47 93.5469 124.352 93.5254 124.244 93.5038L122.856 93.1809L123.857 92.1581C123.932 92.0828 124.029 91.9859 124.158 91.8998C128.271 88.5086 132.071 84.9021 135.462 81.1772C141.168 74.9009 143.622 66.2023 142.018 57.8805H142.029H142.051Z"/>
      <path d="M56.1506 14.0429C65.0861 19.3396 76.9067 27.0801 82.4833 33.8732C83.14 34.659 83.7967 35.4449 84.4534 36.1985C85.6591 37.5873 85.7991 39.5789 84.7979 41.1292C82.9892 43.9174 80.9115 46.6627 78.6399 49.3003C76.9713 51.2165 76.9067 54.0156 78.4785 55.9534L78.5431 56.0288C78.7261 56.2656 78.9306 56.5132 79.1136 56.75C80.7931 58.8816 82.5801 60.9271 84.4211 62.8433C85.4007 63.8661 86.7249 64.4367 88.1352 64.4367L88.2644 65.2333L88.2429 64.4367C89.707 64.4044 91.1173 63.7584 92.0969 62.6388C94.3362 60.1089 96.4247 57.4498 98.3302 54.7691C99.6329 52.9282 102.13 52.5084 104.025 53.8111C105.963 55.146 107.965 56.4163 109.957 57.5897C112.293 58.957 115.114 59.2153 117.665 58.268C120.249 57.3098 122.262 55.2752 123.156 52.6591C124.555 48.6113 122.757 43.9605 118.882 41.6136C116.255 40.0203 113.65 38.2224 111.174 36.2846C109.882 35.2619 109.333 33.5825 109.796 32C110.937 28.0059 111.981 22.8276 112.648 19.1889C113.337 15.4317 111.647 11.5884 108.439 9.65058L108.062 9.43525C105.371 7.83118 102.087 7.71277 99.2668 9.1123C96.4247 10.5226 94.53 13.2463 94.1855 16.3791L94.1639 16.5728C94.1209 16.9604 93.884 17.2511 93.518 17.3695C93.152 17.4879 92.7859 17.3911 92.5168 17.1327C88.5012 12.848 84.238 8.96157 79.8134 5.57041C73.8708 1.01656 66.2811 -0.878188 58.9928 0.381386L58.6805 0.435234C55.6124 0.973513 53.2547 3.30965 52.6949 6.3886C52.1351 9.43527 53.4915 12.4281 56.1722 14.0106H56.1614L56.1506 14.0429Z"/>
    </svg>
  )
}
