const STATUS_CONFIG: Record<string, { label: string; dot: string }> = {
  escalated:   { label: 'Escalated', dot: 'bg-[#e5484d]' },
  in_progress: { label: 'In progress', dot: 'bg-[#d97706]' },
  pending:     { label: 'Pending', dot: 'bg-[#85858b]' },
  recovered:   { label: 'Recovered', dot: 'bg-[#4cc38a]' },
  closed:      { label: 'Closed', dot: 'bg-[#85858b]' },
}

export function StatusPill({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] ?? {
    label: status.replace(/_/g, ' '),
    dot: 'bg-[#85858b]',
  }

  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-secondary whitespace-nowrap">
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot} shrink-0`} />
      <span>{config.label}</span>
    </span>
  )
}
