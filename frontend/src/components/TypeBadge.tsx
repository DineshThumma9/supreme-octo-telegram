const TYPE_LABELS: Record<string, string> = {
  failed_payment:      'Failed payment',
  abandoned_checkout:  'Abandoned checkout',
  failed_subscription: 'Failed subscription',
  overdue_invoice:     'Overdue invoice',
}

export function TypeBadge({ type }: { type: string }) {
  const label = TYPE_LABELS[type] ?? type.replace(/_/g, ' ')
  return (
    <span className="text-xs text-muted whitespace-nowrap">
      {label}
    </span>
  )
}
