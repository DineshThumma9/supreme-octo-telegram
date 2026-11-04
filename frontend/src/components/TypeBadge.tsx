const TYPE_LABELS: Record<string, string> = {
  failed_payment:      'Failed payment',
  abandoned_checkout:  'Abandoned checkout',
  failed_subscription: 'Failed subscription',
  overdue_invoice:     'Overdue invoice',
}

export function TypeBadge({ type }: { type: string }) {
  const label = TYPE_LABELS[type] ?? type.replace(/_/g, ' ')
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-normal text-zinc-400 bg-zinc-900 border border-zinc-800">
      {label}
    </span>
  )
}
