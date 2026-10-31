import React, { useState } from 'react'
import { Button } from '@/components/ui/button'
import { approveEscalation } from '../api'
import type { Case } from '../types'
import { fmt, relTime } from '../utils/formatters'
import { AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react'

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
    <div className="mb-8 rounded-xl border border-red-500/20 bg-red-500/5 overflow-hidden transition-all">
      <div 
        className="px-5 py-3 border-b border-red-500/10 bg-red-500/10 flex items-center justify-between cursor-pointer select-none"
        onClick={() => cases.length > 1 && setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-red-400" />
          <h2 className="text-sm font-semibold text-red-400 tracking-wide uppercase">
            Requires Human Approval ({cases.length})
          </h2>
        </div>
        {cases.length > 1 && (
          <div className="flex items-center gap-1.5 text-xs text-red-400 hover:text-red-300 transition-colors">
            <span>{expanded ? 'Show Less' : `+${cases.length - 1} more`}</span>
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </div>
        )}
      </div>
      <div className="divide-y divide-red-500/10">
        {visibleCases.map((c) => (
          <div
            key={c.case_id}
            onClick={() => onSelect(c.case_id)}
            className="px-5 py-3 hover:bg-red-500/5 cursor-pointer transition-colors flex items-center justify-between gap-4 group"
          >
            <div>
              <p className="text-sm font-medium text-zinc-200">
                {c.customer.name} · <span className="text-red-400 font-semibold">${fmt(c.amount)}</span>
              </p>
              <p className="text-xs text-zinc-500 mt-0.5">
                {c.case_type.replace(/_/g, ' ')} · Escalated {relTime(c.first_seen_at)}
              </p>
            </div>
            <Button
              size="sm"
              onClick={(e) => handleApprove(e, c.case_id)}
              disabled={approving === c.case_id}
              className="bg-red-500/20 text-red-400 hover:bg-red-500/30 hover:text-red-300 opacity-0 group-hover:opacity-100 transition-opacity"
            >
              {approving === c.case_id ? 'Approving…' : 'Approve Action'}
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}
