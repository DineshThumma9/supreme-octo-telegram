import { useState, useEffect } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchCase, approveEscalation, closeCase } from '../api'
import { useCaseStore } from '../store/useCaseStore'
import type { Case } from '../types'
import { fmt, fmtTs } from '../utils/formatters'
import { AuditTimeline } from './AuditTimeline'
import {
  Copy, Check, X, Mail, Phone, AlertTriangle, ShieldCheck, Link2, Tag, Calendar
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
      const newWidth = Math.min(Math.max(startWidth + delta, 440), window.innerWidth - 60)
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

  const handleCloseCase = async () => {
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
    <div className="h-full min-h-0 bg-card text-primary flex flex-col relative w-full overflow-hidden select-none">
      {/* Draggable Resize Handle on Left Edge */}
      <div
        onMouseDown={handleMouseDown}
        className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize select-none z-30"
        title="Drag to resize drawer width"
      >
        <div className="w-0.5 h-10 rounded-sm bg-hover mx-1" />
      </div>

      {/* Loading Skeleton */}
      {loading && (
        <div className="p-4 flex flex-col gap-3 select-auto">
          <div className="flex justify-between items-center">
            <Skeleton className="h-3 w-32 bg-raised" />
            <Skeleton className="h-4 w-4 rounded bg-raised" />
          </div>
          <Skeleton className="h-3 w-48 bg-raised" />
          <Skeleton className="h-3 w-64 bg-raised" />
          <div className="h-px bg-hairline my-2" />
          <Skeleton className="h-32 w-full bg-raised rounded" />
        </div>
      )}

      {/* Error View */}
      {error && !loading && (
        <div className="p-6 flex flex-col items-center justify-center text-center h-full select-auto">
          <AlertTriangle className="w-5 h-5 text-[#e5484d] mb-2" strokeWidth={1.5} />
          <p className="text-xs font-medium text-primary mb-1">{error}</p>
          <p className="text-xs text-muted mb-4 max-w-sm">
            Could not retrieve case details. Please try again.
          </p>
          <button
            onClick={onClose}
            className="h-7 px-3 rounded border border-hairline bg-raised hover:bg-hover text-xs text-secondary"
          >
            Close
          </button>
        </div>
      )}

      {!detail && !loading && !error && (
        <div className="p-6 flex flex-col items-center justify-center text-center h-full text-muted text-xs select-auto">
          Select a case to view details
        </div>
      )}

      {detail && !loading && (
        <div className="flex flex-col h-full min-h-0 select-auto">
          {/* Top Bar: Case ID & Dismiss */}
          <div className="px-4 py-3 border-b border-hairline bg-card flex items-center justify-between shrink-0 z-10">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted">Case ID</span>
              <button
                onClick={handleCopyId}
                className="inline-flex items-center gap-1.5 text-xs font-mono px-2 py-0.5 rounded border border-hairline bg-raised hover:bg-hover text-secondary hover:text-primary transition-colors"
                title="Copy case ID"
              >
                {copied ? (
                  <>
                    <Check className="w-3 h-3 text-[#4cc38a]" />
                    <span className="text-[#4cc38a]">Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3 h-3 text-muted" />
                    <span className="truncate max-w-[200px]">{detail.case_id}</span>
                  </>
                )}
              </button>
            </div>
            <button
              onClick={onClose}
              className="p-1 rounded text-muted hover:text-primary hover:bg-raised transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Scrollable Body */}
          <div className="flex-1 overflow-y-auto overflow-x-hidden min-h-0">
            {/* Customer Profile & Amount */}
            <div className="px-4 py-4 border-b border-hairline space-y-3">
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="space-y-1 min-w-0">
                  <h2 className="text-base font-medium tracking-tight text-primary">
                    {detail.customer.name || 'Unknown customer'}
                  </h2>
                  <div className="flex flex-col items-start gap-y-1 mt-1 text-xs text-muted">
                    {detail.customer.email && (
                      <span className="flex items-center gap-1.5">
                        <Mail className="w-3 h-3 text-muted shrink-0" strokeWidth={1.5} />
                        {detail.customer.email}
                      </span>
                    )}
                    {detail.customer.contact && (
                      <span className="flex items-center gap-1.5">
                        <Phone className="w-3 h-3 text-muted shrink-0" strokeWidth={1.5} />
                        {detail.customer.contact}
                      </span>
                    )}
                  </div>
                </div>

                {/* Amount */}
                <div className="text-right shrink-0">
                  <div className="text-xl font-medium text-primary tracking-tight tabular">
                    ${fmt(detail.amount)}
                  </div>
                  <div className="text-xs text-muted mt-0.5">
                    {detail.recovery_status === 'recovered' ? 'Recovered' : 'Amount at risk'}
                  </div>
                </div>
              </div>

              {/* Metadata Row */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3 border-t border-hairline text-xs">
                <div>
                  <span className="text-muted block text-[11px] mb-0.5">Status</span>
                  <span className="text-secondary font-medium">
                    {detail.recovery_status === 'escalated' ? (
                      <span className="text-[#e5484d]">Escalated</span>
                    ) : detail.recovery_status === 'recovered' ? (
                      <span className="text-[#4cc38a]">Recovered</span>
                    ) : (
                      <span>Active ({detail.attempt_count}/3)</span>
                    )}
                  </span>
                </div>
                <div>
                  <span className="text-muted block text-[11px] mb-0.5">Decline reason</span>
                  <span className="text-secondary block truncate">
                    {detail.failure_reason || detail.decline_type || 'Payment failed'}
                  </span>
                </div>
                <div>
                  <span className="text-muted block text-[11px] mb-0.5">Next contact</span>
                  <span className="text-secondary block truncate tabular">
                    {detail.next_retry_at ? fmtTs(detail.next_retry_at) : '—'}
                  </span>
                </div>
                <div>
                  <span className="text-muted block text-[11px] mb-0.5">Category</span>
                  <span className="text-secondary block truncate capitalize">
                    {detail.case_type.replace(/_/g, ' ')}
                  </span>
                </div>
              </div>
            </div>

            {/* Recovery State Metadata */}
            {detail.case_metadata && Object.keys(detail.case_metadata).length > 0 && (
              <div className="px-4 py-3 border-b border-hairline bg-raised/50 text-xs">
                <span className="text-muted block text-[11px] mb-2">Recovery metadata</span>
                <div className="flex flex-wrap gap-1.5">
                  {detail.case_metadata.payment_link && (
                    <a
                      href={detail.case_metadata.payment_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-hairline bg-raised text-secondary hover:text-primary"
                    >
                      <Link2 className="w-3 h-3 text-muted" />
                      Payment link
                    </a>
                  )}
                  {(detail.case_metadata.payment_link_is_mock ||
                    String(detail.case_metadata.payment_link ?? '').includes('MOCK')) && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-hairline bg-raised text-[#d97706]">
                      Mock link — PayPal not called
                    </span>
                  )}
                  {detail.case_metadata.discount_pct !== undefined && detail.case_metadata.discount_pct > 0 && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-hairline bg-raised text-secondary">
                      <Tag className="w-3 h-3 text-muted" />
                      Discount: {detail.case_metadata.discount_pct}%
                    </span>
                  )}
                  {detail.case_metadata.ptp_date && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-hairline bg-raised text-secondary">
                      <Calendar className="w-3 h-3 text-muted" />
                      PTP: {detail.case_metadata.ptp_date}
                    </span>
                  )}
                  {detail.case_metadata.invoice_number && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-hairline bg-raised text-secondary">
                      Inv #{detail.case_metadata.invoice_number}
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Diagnostic Details */}
            {detail.error_details && Object.keys(detail.error_details).length > 0 && (
              <div className="px-4 py-3 border-b border-hairline text-xs">
                <span className="text-muted block text-[11px] mb-2">Technical diagnostics</span>
                <div className="grid grid-cols-2 gap-2">
                  {detail.error_details.issue && (
                    <div>
                      <span className="text-muted">Code: </span>
                      <span className="text-secondary font-mono">{detail.error_details.issue}</span>
                    </div>
                  )}
                  {(detail.error_details.description || detail.error_details.reason) && (
                    <div className="col-span-2">
                      <span className="text-muted">Reason: </span>
                      <span className="text-secondary">
                        {detail.error_details.description || detail.error_details.reason}
                      </span>
                    </div>
                  )}
                  {detail.error_details.card_brand && (
                    <div>
                      <span className="text-muted">Card: </span>
                      <span className="text-secondary font-mono">
                        {detail.error_details.card_brand} {detail.error_details.card_last4 ? `•••• ${detail.error_details.card_last4}` : ''}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Subheader: Event Audit Trail */}
            <div className="px-4 py-2 border-b border-hairline flex items-center justify-between bg-card sticky top-0 z-10">
              <span className="text-muted text-xs font-medium">Audit trail</span>
              <span className="text-muted text-xs tabular">
                {detail.audit_log?.length || 0} events
              </span>
            </div>

            {/* Timeline Stream */}
            <div className="px-4 py-4 max-w-2xl">
              <AuditTimeline
                entries={detail.audit_log ?? []}
                customerName={detail.customer.name}
              />
            </div>
          </div>

          {/* Bottom Action Footer */}
          <div className="p-3 border-t border-hairline bg-card flex gap-2 shrink-0 z-10">
            {detail.recovery_status === 'escalated' ? (
              <>
                <button
                  onClick={handleApprove}
                  disabled={approving}
                  className="flex-1 h-8 rounded font-medium bg-[#ededed] text-[#141415] hover:bg-white text-xs transition-colors flex items-center justify-center gap-1.5"
                >
                  <ShieldCheck className="w-3.5 h-3.5" strokeWidth={1.5} />
                  {approving ? 'Approving…' : 'Approve & manual retry'}
                </button>
                <button
                  onClick={handleCloseCase}
                  disabled={closing}
                  className="h-8 px-3 rounded border border-hairline bg-raised hover:bg-hover text-secondary hover:text-primary text-xs transition-colors"
                >
                  {closing ? 'Closing…' : 'Close case'}
                </button>
              </>
            ) : (
              <button
                onClick={handleCloseCase}
                disabled={closing}
                className="w-full h-8 rounded border border-hairline bg-raised hover:bg-hover text-secondary hover:text-primary text-xs transition-colors"
              >
                {closing ? 'Closing case…' : 'Mark case as closed'}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
