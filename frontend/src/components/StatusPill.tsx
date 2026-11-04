const STATUS_STYLES: Record<string, string> = {
  escalated:   'text-red-400 bg-red-500/10 border-red-500/20',
  in_progress: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  pending:     'text-zinc-400 bg-zinc-800/40 border-zinc-700/40',
  recovered:   'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  closed:      'text-zinc-500 bg-zinc-850 border-zinc-800',
}

const STATUS_LABELS: Record<string, string> = {
  escalated: 'Escalated',
  in_progress: 'In progress',
  pending: 'Pending',
  recovered: 'Recovered',
  closed: 'Closed',
}

export function StatusPill({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? 'text-zinc-400 bg-zinc-800/40 border-zinc-700/40'
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-normal border ${style}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  )
}
