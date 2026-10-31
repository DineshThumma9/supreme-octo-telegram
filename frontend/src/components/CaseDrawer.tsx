import { useState, useEffect } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { fetchCase, approveEscalation, closeCase } from '../api'
import { useCaseStore } from '../store/useCaseStore'
import type { Case } from '../types'
import { fmt, fmtTs } from '../utils/formatters'
import { AuditTimeline } from './AuditTimeline'
import { 
  Copy, 
  Check, 
  X, 
  Mail, 
  Phone, 
  AlertTriangle, 
  ShieldCheck,
  Link2,
  Tag,
  Calendar
} from 'lucide-react'

export function CaseDrawer({
  caseId,
  open,
  onClose,
  onAction,
  width,
  onResize,
}: {
  caseId: string | null
  open: boolean
  onClose: () => void
  onAction: () => void
  width: number
  onResize: (width: number) => void
}) {
  const [detail, setDetail] = useState<Case | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [approving, setApproving] = useState(false)
  const [closing, setClosing] = useState(false)
  const [copied, setCopied] = useState(false)

  const storeCase = useCaseStore(state => state.cases.find(c => c.case_id === caseId))

  useEffect(() => {
    if (storeCase && open) {
      setDetail(storeCase)
    }
  }, [storeCase, open])

  useEffect(() => {
    if (!caseId || !open) return
    if (storeCase) {
      setDetail(storeCase)
      setLoading(false)
    } else {
      setLoading(true)
      setDetail(null)
    }
    setError(null)
    setCopied(false)
    fetchCase(caseId)
      .then(setDetail)
      .catch((err) => {
        if (!storeCase) {
          setError(err?.message || 'Failed to load case details')
        }
      })
      .finally(() => setLoading(false))
  }, [caseId, open])

  const handleCopyId = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!detail?.case_id) return
    navigator.clipboard.writeText(detail.case_id)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startWidth = width
    const onMouseMove = (moveEvent: MouseEvent) => {
      const delta = startX - moveEvent.clientX
      const newWidth = Math.min(Math.max(startWidth + delta, 460), window.innerWidth - 60)
      onResize(newWidth)
    }
    const onMouseUp = () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }

  const handleApprove = async () => {
    if (!detail) return
    setApproving(true)
    try {
      await approveEscalation(detail.case_id)
      onAction()
      onClose()
    } finally {
      setApproving(false)
    }
  }

  const handleClose = async () => {
    if (!detail) return
    setClosing(true)
    try {
      await closeCase(detail.case_id)
      onAction()
      onClose()
    } finally {
      setClosing(false)
    }
  }

  return (
    <div className="h-full min-h-0 bg-[#0d1117] text-zinc-100 flex flex-col relative w-full overflow-hidden select-none">
      {/* Draggable Resize Handle on Left Edge */}
      <div
        onMouseDown={handleMouseDown}
        className="absolute left-0 top-0 bottom-0 w-2.5 -translate-x-1 cursor-col-resize hover:bg-blue-500/40 active:bg-blue-500 flex items-center justify-center group z-30 transition-colors"
        title="Drag to resize drawer width"
      >
        <div className="w-1 h-7 rounded-full bg-zinc-700 group-hover:bg-blue-400 transition-colors" />
      </div>

      {/* Loading Skeleton */}
      {loading && (
        <div className="p-8 flex flex-col gap-6 select-auto">
          <div className="flex justify-between items-center">
            <Skeleton className="h-5 w-32 bg-zinc-800" />
            <Skeleton className="h-7 w-7 rounded-md bg-zinc-800" />
          </div>
          <Skeleton className="h-9 w-64 bg-zinc-800" />
          <Skeleton className="h-4 w-80 bg-zinc-800" />
          <div className="h-px bg-zinc-800/60 my-2" />
          <Skeleton className="h-40 w-full bg-zinc-800 rounded-xl" />
        </div>
      )}

      {/* Error View */}
      {error && !loading && (
        <div className="p-12 flex flex-col items-center justify-center text-center h-full select-auto">
          <AlertTriangle className="w-9 h-9 text-rose-400 mb-3" />
          <p className="text-sm text-rose-300 font-semibold mb-1">{error}</p>
          <p className="text-xs text-zinc-500 mb-6 max-w-sm">
            Could not retrieve case details. Please try again or refresh the dashboard.
          </p>
          <Button variant="outline" size="sm" onClick={onClose} className="border-zinc-700 text-zinc-300">
            Close
          </Button>
        </div>
      )}

      {!detail && !loading && !error && (
        <div className="p-12 flex flex-col items-center justify-center text-center h-full text-zinc-500 text-sm select-auto">
          Select a case to view its details
        </div>
      )}

      {detail && !loading && (
        <div className="flex flex-col h-full min-h-0 select-auto">
          {/* Top Bar: Case ID & Dismiss (Sticky Header) */}
          <div className="px-8 py-3.5 border-b border-zinc-800/60 bg-[#0d1117] flex items-center justify-between shrink-0 z-10">
            <div className="flex items-center gap-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
                Case File
              </span>
              <button
                onClick={handleCopyId}
                className="inline-flex items-center gap-1.5 text-xs font-sans px-2 py-0.5 rounded bg-zinc-900 border border-zinc-800 hover:border-zinc-700 text-zinc-400 hover:text-zinc-200 transition-colors"
                title="Click to copy case ID"
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                    <span className="text-emerald-400 font-medium">Copied ID</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5 text-zinc-500" />
                    <span className="truncate max-w-[200px]">{detail.case_id}</span>
                  </>
                )}
              </button>
            </div>
            <button
              onClick={onClose}
              className="p-1 rounded-md text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Scrollable Body: Customer Details, Metadata, and Full Audit Timeline */}
          <div className="flex-1 overflow-y-auto overflow-x-hidden min-h-0">
            {/* Customer Profile & Amount (Clean, Uncluttered) */}
            <div className="px-8 py-5 border-b border-zinc-800/60 space-y-4">
              <div className="flex items-start justify-between gap-6 flex-wrap">
                <div className="space-y-1 min-w-0">
                  <h2 className="text-2xl font-bold tracking-tight text-white">
                    {detail.customer.name || 'Unknown Customer'}
                  </h2>
                  <div className="flex flex-col items-start gap-y-1.5 mt-2 text-xs text-zinc-400">
                    {detail.customer.email && (
                      <span className="flex items-center gap-1.5">
                        <Mail className="w-3.5 h-3.5 text-zinc-500" />
                        {detail.customer.email}
                      </span>
                    )}
                    {detail.customer.contact && (
                      <span className="flex items-center gap-1.5">
                        <Phone className="w-3.5 h-3.5 text-zinc-500" />
                        {detail.customer.contact}
                      </span>
                    )}
                  </div>
                </div>

                {/* Clean Amount */}
                <div className="text-right shrink-0">
                  <div className="text-2xl font-bold text-zinc-100 tracking-tight">
                    ${fmt(detail.amount)}
                  </div>
                  <div className="text-[11px] text-zinc-500 uppercase tracking-wider mt-0.5">
                    {detail.recovery_status === 'recovered' ? 'Recovered' : 'Amount at Risk'}
                  </div>
                </div>
              </div>

              {/* Clean Metadata Row */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-3 border-t border-zinc-800/40 text-xs">
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-zinc-500 block mb-0.5">Status</span>
                  <span className="inline-flex items-center gap-1.5 font-medium text-zinc-200">
                    {detail.recovery_status === 'escalated' ? (
                      <>
                        <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />
                        <span className="text-rose-400">Escalated</span>
                      </>
                    ) : detail.recovery_status === 'recovered' ? (
                      <>
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                        <span className="text-emerald-400">Recovered</span>
                      </>
                    ) : (
                      <>
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                        <span>Active ({detail.attempt_count}/3)</span>
                      </>
                    )}
                  </span>
                </div>

                <div>
                  <span className="text-[10px] uppercase tracking-wider text-zinc-500 block mb-0.5">Decline Cause</span>
                  <span className="font-medium text-zinc-200 block truncate">
                    {detail.failure_reason || detail.decline_type || 'Payment Failed'}
                  </span>
                </div>

                <div>
                  <span className="text-[10px] uppercase tracking-wider text-zinc-500 block mb-0.5">Next Contact</span>
                  <span className="font-medium text-zinc-300 block truncate">
                    {detail.next_retry_at ? fmtTs(detail.next_retry_at) : '—'}
                  </span>
                </div>

                <div>
                  <span className="text-[10px] uppercase tracking-wider text-zinc-500 block mb-0.5">Category</span>
                  <span className="text-zinc-300 block capitalize truncate">
                    {detail.case_type.replace(/_/g, ' ')}
                  </span>
                </div>
              </div>
            </div>

            {/* Recovery State Metadata */}
            {detail.case_metadata && Object.keys(detail.case_metadata).length > 0 && (
              <div className="px-8 py-3.5 border-b border-zinc-800/40 bg-zinc-900/30 text-xs">
                <span className="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold block mb-2">
                  Recovery State Intelligence
                </span>
                <div className="flex flex-wrap gap-2 text-[11px]">
                  {detail.case_metadata.payment_link && (
                    <a
                      href={detail.case_metadata.payment_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-indigo-950/60 border border-indigo-700/50 text-indigo-300 hover:text-indigo-100"
                    >
                      <Link2 className="w-3 h-3" />
                      Payment Link
                    </a>
                  )}
                  {detail.case_metadata.discount_pct !== undefined && detail.case_metadata.discount_pct > 0 && (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-emerald-950/60 border border-emerald-700/50 text-emerald-300">
                      <Tag className="w-3 h-3" />
                      Concession: {detail.case_metadata.discount_pct}%
                    </span>
                  )}
                  {detail.case_metadata.ptp_date && (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-amber-950/60 border border-amber-700/50 text-amber-300">
                      <Calendar className="w-3 h-3" />
                      PTP: {detail.case_metadata.ptp_date}
                    </span>
                  )}
                  {detail.case_metadata.cumulative_grace_days_used !== undefined && (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-800/80 border border-zinc-700/50 text-zinc-300">
                      Grace Used: {detail.case_metadata.cumulative_grace_days_used}d
                    </span>
                  )}
                  {detail.case_metadata.invoice_number && (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-800/80 border border-zinc-700/50 text-zinc-300">
                      Inv #{detail.case_metadata.invoice_number}
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Diagnostic Details */}
            {detail.error_details && Object.keys(detail.error_details).length > 0 && (
              <div className="px-8 py-3.5 border-b border-zinc-800/40 bg-rose-950/10 text-xs">
                <span className="text-[10px] uppercase tracking-wider text-rose-400/80 font-semibold block mb-2">
                  Technical Diagnostics
                </span>
                <div className="grid grid-cols-2 gap-2 text-[11px] text-zinc-400">
                  {detail.error_details.error_code && (
                    <div>
                      <span className="text-zinc-500">Code:</span> <span className="text-rose-300 font-mono">{detail.error_details.error_code}</span>
                    </div>
                  )}
                  {detail.error_details.error_step && (
                    <div>
                      <span className="text-zinc-500">Step:</span> <span className="text-zinc-300">{detail.error_details.error_step}</span>
                    </div>
                  )}
                  {detail.error_details.error_reason && (
                    <div className="col-span-2">
                      <span className="text-zinc-500">Reason:</span> <span className="text-zinc-300">{detail.error_details.error_reason}</span>
                    </div>
                  )}
                  {detail.error_details.card_network && (
                    <div>
                      <span className="text-zinc-500">Card:</span> <span className="text-zinc-300">{detail.error_details.card_network} {detail.error_details.card_last4 ? `•••• ${detail.error_details.card_last4}` : ''}</span>
                    </div>
                  )}
                  {detail.error_details.rrn && (
                    <div>
                      <span className="text-zinc-500">RRN:</span> <span className="text-zinc-300 font-mono">{detail.error_details.rrn}</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Subheader: Event Audit Trail (Sticky under Top Bar while scrolling) */}
            <div className="px-8 py-2.5 border-b border-zinc-800/50 flex items-center justify-between text-xs bg-[#0d1117]/95 sticky top-0 z-10 backdrop-blur-sm">
              <span className="font-semibold font-sans uppercase tracking-wider text-zinc-400 text-[11px]">
                Audit Trail 
              </span>
              <span className="text-[11px] font-sans text-zinc-500">
                {detail.audit_log?.length || 0} events
              </span>
            </div>

            {/* Timeline Stream */}
            <div className="px-8 py-6 max-w-2xl">
              <AuditTimeline 
                entries={detail.audit_log ?? []} 
                customerName={detail.customer.name}
              />
            </div>
          </div>

          {/* Bottom Action Footer (Sticky at Bottom) */}
          <div className="p-4 border-t border-zinc-800 bg-[#0d1117] flex gap-3 shrink-0 z-10">
            {detail.recovery_status === 'escalated' ? (
              <>
                <Button
                  onClick={handleApprove}
                  disabled={approving}
                  className="flex-1 font-semibold h-10 bg-amber-500 hover:bg-amber-600 text-zinc-950 shadow-sm text-xs"
                >
                  <ShieldCheck className="w-4 h-4 mr-1.5" />
                  {approving ? 'Approving...' : 'Approve & Manual Retry'}
                </Button>
                <Button
                  variant="outline"
                  onClick={handleClose}
                  disabled={closing}
                  className="h-10 px-4 border-zinc-700 bg-zinc-900 hover:bg-zinc-800 text-zinc-300 text-xs"
                >
                  {closing ? 'Closing...' : 'Close Case'}
                </Button>
              </>
            ) : (
              <Button
                variant="outline"
                onClick={handleClose}
                disabled={closing}
                className="w-full h-9 border-zinc-800 bg-zinc-900 hover:bg-zinc-800 text-zinc-300 text-xs"
              >
                {closing ? 'Closing Case...' : 'Mark Case as Closed'}
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
