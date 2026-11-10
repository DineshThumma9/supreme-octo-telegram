import React, { useState } from 'react'
import { approveEscalation } from '../api'
import type { Case } from '../types'
import { fmt, relTime } from '../utils/formatters'
import { ChevronDown, ChevronUp } from 'lucide-react'

export function EscalationPanel({
  cases,
  onSelect,
  onApprove,
}: {
  cases: Case[]
  onSelect: (id: string) => void
  onApprove: () => void
}) {
  const [approving, setApproving] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  if (cases.length === 0) return null

  const handleApprove = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    setApproving(id)
    try {
      await approveEscalation(id)
      onApprove()
    } finally {
      setApproving(null)
    }
  }

  const visibleCases = expanded ? cases : cases.slice(0, 1)

  return (
    <div className="mb-6 rounded-lg border border-hairline bg-card overflow-hidden">
      <div
        className="px-4 py-3 border-b border-hairline flex items-center justify-between cursor-pointer select-none"
        onClick={() => cases.length > 1 && setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-[#e5484d]" />
          <h2 className="text-xs font-medium text-primary">
            Requires human approval ({cases.length})
          </h2>
        </div>
        {cases.length > 1 && (
          <button className="flex items-center gap-1 text-[11px] text-muted hover:text-secondary">
            <span>{expanded ? 'Show fewer' : `+${cases.length - 1} more`}</span>
            {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        )}
      </div>

      <div className="divide-y divide-hairline">
        {visibleCases.map((c) => (
          <div
            key={c.case_id}
            onClick={() => onSelect(c.case_id)}
            className="px-4 py-3 hover:bg-raised/40 cursor-pointer transition-colors flex items-center justify-between gap-4"
          >
            <div>
              <p className="text-xs font-medium text-primary">
                {c.customer.name} · <span className="tabular font-normal text-secondary">${fmt(c.amount)}</span>
              </p>
              <p className="text-[11px] text-muted mt-0.5">
                {c.case_type.replace(/_/g, ' ')} · Escalated {relTime(c.first_seen_at)}
              </p>
            </div>

            <button
              onClick={(e) => handleApprove(e, c.case_id)}
              disabled={approving === c.case_id}
              className="h-7 px-2.5 rounded border border-hairline bg-raised hover:bg-hover text-xs text-primary transition-colors disabled:opacity-50"
            >
              {approving === c.case_id ? 'Approving…' : 'Approve action'}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
