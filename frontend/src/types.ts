import { z } from 'zod'

export const CustomerSchema = z.object({
  name: z.string().default('Unknown'),
  email: z.string().default(''),
  contact: z.string().default(''),
})

export const AuditEntrySchema = z.object({
  event_triggered: z.string(),
  amount: z.string(),
  recovery_status: z.string(),
  customer: CustomerSchema,
  next_contact: z.string().nullable().optional(),
  message: z.string().nullable().optional(),
  channel: z.string().nullable().optional(),
  direction: z.string().nullable().optional(),
  created_at: z.string().nullable().optional(),
})

export const CaseSchema = z.object({
  case_id: z.string(),
  case_type: z.string(),
  decline_type: z.string().nullable(),
  failure_reason: z.string().nullable(),
  amount: z.number(),
  recovered_amount: z.number().default(0),
  customer: CustomerSchema,
  recovery_status: z.string(),
  attempt_count: z.number(),
  last_action_taken: z.string().nullable(),
  first_seen_at: z.string().nullable(),
  next_retry_at: z.string().nullable(),
  language: z.string().default('english'),
  audit_log: z.array(AuditEntrySchema).optional(),
  source_id: z.string().optional(),
  error_details: z.record(z.string(), z.any()).optional(),
  case_metadata: z.record(z.string(), z.any()).optional(),
})

export const StatsSchema = z.object({
  total_cases: z.number(),
  total_at_risk: z.number(),
  recovered_count: z.number(),
  recovered_amount: z.number(),
  recovery_rate_pct: z.number(),
  escalated_count: z.number(),
  still_active: z.number(),
})

export type Customer = z.infer<typeof CustomerSchema>
export type AuditEntry = z.infer<typeof AuditEntrySchema>
export type Case = z.infer<typeof CaseSchema>
export type Stats = z.infer<typeof StatsSchema>
