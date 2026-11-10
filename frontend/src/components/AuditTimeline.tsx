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

const EVENT_STYLES: Record<string, { title: string; class: string }> = {
  payment_failed: { title: 'Payment failed', class: 'text-negative bg-negative/10 border-negative' },
  customer_reply: { title: 'Customer reply', class: 'text-secondary bg-zinc-900 border-zinc-700' },
  send_whatsapp_msg: { title: 'WhatsApp dispatched', class: 'text-secondary bg-zinc-900 border-zinc-700' },
  send_email_reminder: { title: 'Email reminder sent', class: 'text-secondary bg-zinc-900 border-zinc-700' },
  get_voice_call: { title: 'Voice note dispatched', class: 'text-secondary bg-zinc-900 border-zinc-700' },
  create_payment_link: { title: 'PayPal payment link created', class: 'text-amber-600 bg-amber-600/10 border-amber-600' },
  escalate_to_human: { title: 'Escalated to human', class: 'text-negative bg-negative/10 border-negative' },
  get_next_payday_date: { title: 'Payday milestone', class: 'text-secondary bg-zinc-900 border-zinc-700' },
  log_promise_to_pay: { title: 'Promise to pay recorded', class: 'text-amber-600 bg-amber-600/10 border-amber-600' },
  complete_case: { title: 'Case resolved — recovered', class: 'text-positive bg-positive/10 border-positive' },
}

export function AuditTimeline({
  entries,
  customerName,
}: {
  entries: AuditEntry[]
  customerName?: string
}) {
  if (!entries || entries.length === 0) {
    return (
      <div className="py-8 text-center text-[11px] text-muted">
        No events recorded yet.
      </div>
    )
  }

  const chronological = [...entries]

  return (
    <Timeline defaultValue={chronological.length} className="w-full">
      {chronological.map((e, idx) => {
        const isCustomer = e.direction === 'inbound' || e.event_triggered === 'customer_reply'
        const key = isCustomer ? 'customer_reply' : e.event_triggered
        const style = EVENT_STYLES[key] ?? { title: 'System event', class: 'text-muted bg-zinc-900 border-zinc-800' }
        const title = isCustomer ? `${style.title} (${customerName || 'Customer'})` : style.title

        return (
          <TimelineItem key={idx} step={idx + 1}>
            <TimelineHeader>
              <TimelineDate className="text-muted text-[10px] font-mono tabular">
                {e.created_at ? fmtTs(e.created_at) : ''}
              </TimelineDate>
              <TimelineTitle className="text-secondary text-xs font-medium">{title}</TimelineTitle>
            </TimelineHeader>

            <TimelineIndicator className={`${style.class} size-3 rounded-full border-2`} />
            <TimelineSeparator className="bg-hairline/50" />

            <TimelineContent className="mt-2 space-y-2">
              {e.message && (
                isCustomer ? (
                  <Bubble variant="inbound" className="border-hairline text-secondary">
                    {e.message}
                  </Bubble>
                ) : e.event_triggered === 'create_payment_link' ? (
                  <div className="rounded-md border border-hairline bg-zinc-900 p-2 text-[10px] font-mono text-secondary break-all">
                    {e.message}
                  </div>
                ) : (
                  <p className="text-[11px] text-muted leading-relaxed">{e.message}</p>
                )
              )}

              {e.next_contact && (
                <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border border-hairline bg-zinc-900 text-[10px] text-muted">
                  <Calendar className="w-2.5 h-2.5 text-zinc-500" strokeWidth={1.5} />
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
