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
        let title = "System Event"
        let indicatorClass = "border-zinc-600 bg-zinc-800"

        if (isInitialFailure) {
          title = `Payment Failed · $${e.amount}`
          indicatorClass = "border-rose-500 bg-rose-500/20 text-rose-400"
        } else if (isCustomer) {
          title = `Customer Reply (${customerName || 'Customer'})`
          indicatorClass = "border-emerald-500 bg-emerald-500/20 text-emerald-400"
        } else if (isWhatsApp) {
          title = "WhatsApp Outreach Dispatched"
          indicatorClass = "border-blue-500 bg-blue-500/20 text-blue-400"
        } else if (isEmail) {
          title = "Email Reminder Sent"
          indicatorClass = "border-indigo-500 bg-indigo-500/20 text-indigo-400"
        } else if (isVoice) {
          title = "AI Voice Note Dispatched"
          indicatorClass = "border-purple-500 bg-purple-500/20 text-purple-400"
        } else if (isPaymentLink) {
          title = "PayPal Payment Link Generated"
          indicatorClass = "border-sky-500 bg-sky-500/20 text-sky-400"
        } else if (isEscalation) {
          title = "Escalated to Human Operations"
          indicatorClass = "border-amber-500 bg-amber-500/20 text-amber-400"
        } else if (isSalary) {
          title = "Payday Milestone Calculated"
          indicatorClass = "border-teal-500 bg-teal-500/20 text-teal-400"
        } else if (isPromiseToPay) {
          title = "Promise-to-Pay Recorded"
          indicatorClass = "border-indigo-500 bg-indigo-500/20 text-indigo-400"
        } else if (e.event_triggered === 'complete_case') {
          title = "Case Resolved & Payment Recovered"
          indicatorClass = "border-emerald-400 bg-emerald-500/20 text-emerald-400"
        }

        return (
          <TimelineItem key={idx} step={idx + 1}>
            <TimelineHeader>
              <TimelineDate className="text-zinc-500 text-[11px] font-medium">
                {e.created_at ? fmtTs(e.created_at) : ''}
              </TimelineDate>
              <TimelineTitle className="text-zinc-200 text-xs font-semibold">
                {title}
              </TimelineTitle>
            </TimelineHeader>

            <TimelineIndicator className={indicatorClass} />
            <TimelineSeparator className="bg-zinc-800" />

            <TimelineContent className="mt-1 space-y-2">
              {e.message && (
                isCustomer ? (
                  <Bubble variant="inbound" className="text-xs bg-zinc-900 border border-zinc-800 text-zinc-200">
                    {e.message}
                  </Bubble>
                ) : isWhatsApp ? (
                  <Bubble variant="outbound" className="text-xs bg-blue-950/40 border border-blue-800/40 text-blue-100">
                    {e.message}
                  </Bubble>
                ) : isEmail ? (
                  <div className="rounded-lg bg-zinc-900 border border-zinc-800 p-2.5 text-xs text-zinc-300">
                    {e.message}
                  </div>
                ) : isPaymentLink ? (
                  <div className="rounded-lg bg-zinc-900 border border-zinc-800 p-2.5 text-xs">
                    <p className="text-sky-400 font-medium break-all">{e.message}</p>
                  </div>
                ) : (
                  <p className="text-xs text-zinc-400 leading-relaxed">
                    {e.message}
                  </p>
                )
              )}

              {e.next_contact && (
                <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-zinc-900 border border-zinc-800 text-zinc-400">
                  <Calendar className="w-3 h-3 text-indigo-400" />
                  <span>Next follow-up: {fmtTs(e.next_contact)}</span>
                </div>
              )}
            </TimelineContent>
          </TimelineItem>
        )
      })}
    </Timeline>
  )
}
