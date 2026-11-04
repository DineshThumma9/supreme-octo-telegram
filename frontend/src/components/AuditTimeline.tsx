import type { AuditEntry } from '../types'
import { fmtTs } from '../utils/formatters'
import {
  Timeline,
  TimelineContent,
  TimelineDate,
  TimelineHeader,
  TimelineIndicator,
  TimelineItem,
  TimelineSeparator,
  TimelineTitle,
} from "@/components/reui/timeline"
import { Bubble } from "@/components/ui/bubble"
import { Calendar } from "lucide-react"

export function AuditTimeline({ 
  entries, 
  customerName, 
}: { 
  entries: AuditEntry[]
  customerName?: string
}) {
  if (!entries || entries.length === 0) {
    return (
      <div className="py-8 text-center text-xs text-zinc-500">
        No events recorded yet.
      </div>
    )
  }

  const chronological = [...entries]

  return (
    <Timeline defaultValue={chronological.length} className="w-full">
      {chronological.map((e, idx) => {
        const isWhatsApp = e.channel === 'whatsapp' || e.event_triggered === 'send_whatsapp_msg'
        const isEmail = e.channel === 'email' || e.event_triggered === 'send_email_reminder'
        const isCustomer = e.direction === 'inbound' || e.event_triggered === 'customer_reply'
        const isPaymentLink = e.channel === 'link' || e.event_triggered === 'create_payment_link'
        const isEscalation = e.event_triggered === 'escalate_to_human'
        const isInitialFailure = e.event_triggered === 'payment_failed'
        const isSalary = e.event_triggered === 'get_next_payday_date'
        const isPromiseToPay = e.event_triggered === 'log_promise_to_pay'
        const isVoice = e.channel === 'voice' || e.event_triggered === 'get_voice_call'

        // Determine title & indicator styling
        let title = "System event"
        let indicatorClass = "border-zinc-700 bg-zinc-800"

        if (isInitialFailure) {
          title = `Payment failed · $${e.amount}`
          indicatorClass = "border-rose-500/80 bg-rose-500/20 text-rose-400"
        } else if (isCustomer) {
          title = `Customer reply (${customerName || 'Customer'})`
          indicatorClass = "border-zinc-500 bg-zinc-800 text-zinc-300"
        } else if (isWhatsApp) {
          title = "WhatsApp outreach dispatched"
          indicatorClass = "border-zinc-500 bg-zinc-800 text-zinc-300"
        } else if (isEmail) {
          title = "Email reminder sent"
          indicatorClass = "border-zinc-500 bg-zinc-800 text-zinc-300"
        } else if (isVoice) {
          title = "Voice note dispatched"
          indicatorClass = "border-zinc-500 bg-zinc-800 text-zinc-300"
        } else if (isPaymentLink) {
          title = "PayPal payment link generated"
          indicatorClass = "border-amber-500/80 bg-amber-500/20 text-amber-400"
        } else if (isEscalation) {
          title = "Escalated to human operations"
          indicatorClass = "border-red-500/80 bg-red-500/20 text-red-400"
        } else if (isSalary) {
          title = "Payday milestone calculated"
          indicatorClass = "border-zinc-500 bg-zinc-800 text-zinc-300"
        } else if (isPromiseToPay) {
          title = "Promise to pay recorded"
          indicatorClass = "border-amber-500/80 bg-amber-500/20 text-amber-400"
        } else if (e.event_triggered === 'complete_case') {
          title = "Case resolved and payment recovered"
          indicatorClass = "border-emerald-500/80 bg-emerald-500/20 text-emerald-400"
        }

        return (
          <TimelineItem key={idx} step={idx + 1}>
            <TimelineHeader>
              <TimelineDate className="text-zinc-500 text-[11px] font-normal tabular">
                {e.created_at ? fmtTs(e.created_at) : ''}
              </TimelineDate>
              <TimelineTitle className="text-zinc-200 text-xs font-medium">
                {title}
              </TimelineTitle>
            </TimelineHeader>

            <TimelineIndicator className={indicatorClass} />
            <TimelineSeparator className="bg-zinc-800" />

            <TimelineContent className="mt-1 space-y-2">
              {e.message && (
                isCustomer ? (
                  <Bubble variant="inbound" className="text-xs bg-zinc-900 border border-zinc-800 text-zinc-200 rounded-md">
                    {e.message}
                  </Bubble>
                ) : isWhatsApp ? (
                  <Bubble variant="outbound" className="text-xs bg-zinc-900 border border-zinc-800 text-zinc-200 rounded-md">
                    {e.message}
                  </Bubble>
                ) : isEmail ? (
                  <div className="rounded-md bg-zinc-900 border border-zinc-800 p-2.5 text-xs text-zinc-300">
                    {e.message}
                  </div>
                ) : isPaymentLink ? (
                  <div className="rounded-md bg-zinc-900 border border-zinc-800 p-2.5 text-xs">
                    <p className="text-amber-400/90 font-normal break-all font-mono">{e.message}</p>
                  </div>
                ) : (
                  <p className="text-xs text-zinc-400 leading-relaxed">
                    {e.message}
                  </p>
                )
              )}

              {e.next_contact && (
                <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-normal bg-zinc-900 border border-zinc-800 text-zinc-400">
                  <Calendar className="w-3 h-3 text-zinc-500" strokeWidth={1.5} />
                  <span>Next follow-up: <span className="tabular">{fmtTs(e.next_contact)}</span></span>
                </div>
              )}
            </TimelineContent>
          </TimelineItem>
        )
      })}
    </Timeline>
  )
}
