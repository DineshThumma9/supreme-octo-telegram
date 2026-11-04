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
    <div className="mb-8 rounded-lg border border-red-900/40 bg-zinc-900/40 overflow-hidden">
      <div 
        className="px-4 py-2.5 border-b border-red-900/30 bg-red-950/20 flex items-center justify-between cursor-pointer select-none"
        onClick={() => cases.length > 1 && setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0" strokeWidth={1.5} />
          <h2 className="text-xs font-medium text-red-400">
            Requires human approval ({cases.length})
          </h2>
        </div>
        {cases.length > 1 && (
          <div className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 transition-colors">
            <span>{expanded ? 'Show less' : `+${cases.length - 1} more`}</span>
            {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </div>
        )}
      </div>
      <div className="divide-y divide-zinc-800/60">
        {visibleCases.map((c) => (
          <div
            key={c.case_id}
            onClick={() => onSelect(c.case_id)}
            className="px-4 py-2.5 hover:bg-zinc-800/30 cursor-pointer transition-colors flex items-center justify-between gap-4 group"
          >
            <div>
              <p className="text-xs font-medium text-zinc-200">
                {c.customer.name} · <span className="text-zinc-100 tabular">${fmt(c.amount)}</span>
              </p>
              <p className="text-[11px] text-zinc-500 mt-0.5">
                {c.case_type.replace(/_/g, ' ')} · Escalated {relTime(c.first_seen_at)}
              </p>
            </div>
            <Button
              size="sm"
              onClick={(e) => handleApprove(e, c.case_id)}
              disabled={approving === c.case_id}
              className="bg-zinc-800 hover:bg-zinc-700 text-red-400 border border-zinc-700/60 h-7 text-xs rounded-md opacity-0 group-hover:opacity-100 transition-opacity"
            >
              {approving === c.case_id ? 'Approving…' : 'Approve action'}
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}
