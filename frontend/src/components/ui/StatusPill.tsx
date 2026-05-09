

export default function StatusPill({ status }: { status: 'healthy' | 'attention' | 'critical' | 'analyzing' | 'unknown' }) {
  const map: Record<string, { dot: string; labelClass?: string }> = {
    healthy: { dot: 'bg-green-500', labelClass: 'text-green-400' },
    attention: { dot: 'bg-yellow-500', labelClass: 'text-yellow-400' },
    critical: { dot: 'bg-red-500', labelClass: 'text-red-400' },
    analyzing: { dot: 'bg-blue-500', labelClass: 'text-blue-400' },
    unknown: { dot: 'bg-gray-400', labelClass: 'text-gray-400' },
  }

  const cfg = map[status] || map.unknown

  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span className={`w-2 h-2 rounded-full ${cfg.dot} flex-shrink-0`} />
      <span className={cfg.labelClass}>{status}</span>
    </span>
  )
}
