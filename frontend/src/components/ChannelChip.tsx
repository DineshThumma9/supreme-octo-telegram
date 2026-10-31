import React from 'react'
import {
  MessageCircle,
  Mail,
  Phone,
  Link as LinkIcon,
  AlertTriangle,
  Calendar,
  BarChart,
  CheckCircle,
  Zap,
  RefreshCw,
  CreditCard,
  Tag,
  PauseCircle,
  FileText,
} from 'lucide-react'

export const CHANNEL_ICONS: Record<string, React.ElementType> = {
  send_whatsapp_msg:  MessageCircle,
  send_email_reminder:Mail,
  get_voice_call:     Phone,
  create_payment_link:LinkIcon,
  escalate_to_human:  AlertTriangle,
  log_promise_to_pay: Calendar,
  get_next_payday_date:BarChart,
  complete_case:      CheckCircle,
  play_email_link:    Mail,
  play_sms_link:      MessageCircle,
  play_paypal_invoice_reminder: FileText,
  play_retry_now:     RefreshCw,
  play_retry_payday:  Calendar,
  play_update_method_link: CreditCard,
  play_discount_link: Tag,
  play_human_escalation: AlertTriangle,
  play_no_contact:    PauseCircle,
  contact_window_deferred: PauseCircle,
  payment_recovered:  CheckCircle,
}

export const CHANNEL_LABEL: Record<string, string> = {
  send_whatsapp_msg:   'WhatsApp',
  send_email_reminder: 'Email',
  get_voice_call:      'Voice',
  create_payment_link: 'Payment Link',
  escalate_to_human:   'Escalated',
  log_promise_to_pay:  'Promise',
  get_next_payday_date:'Payday',
  complete_case:       'Completed',
  play_email_link:     'Email Link',
  play_sms_link:       'SMS / WhatsApp',
  play_paypal_invoice_reminder: 'Invoice Reminder',
  play_retry_now:      'Retry Now',
  play_retry_payday:   'Retry Payday',
  play_update_method_link: 'Update Method',
  play_discount_link:  'Discount Link',
  play_human_escalation: 'Escalated',
  play_no_contact:     'No Contact',
  contact_window_deferred: 'Deferred',
  payment_recovered:   'Recovered',
}

export function ChannelChip({ action }: { action: string | null }) {
  if (!action) return <span className="text-zinc-600 text-xs">—</span>
  const Icon = CHANNEL_ICONS[action] ?? Zap
  const label = CHANNEL_LABEL[action] ?? action.replace(/_/g, ' ')
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-zinc-400">
      <Icon className="w-3.5 h-3.5 text-zinc-500" />
      <span>{label}</span>
    </span>
  )
}
