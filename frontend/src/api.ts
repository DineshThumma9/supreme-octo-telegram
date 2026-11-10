import { z } from 'zod'
import { CaseSchema, StatsSchema, type Case, type Stats } from './types'

export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`)
  }
  return res.json()
}

// Generic helper: parse + validate response with a Zod schema
async function get<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const data = await request<unknown>(path)
  return schema.parse(data)
}

export async function fetchCases(): Promise<Case[]> {
  return get('/cases', z.array(CaseSchema))
}

export async function fetchCase(caseId: string): Promise<Case> {
  return get(`/cases/${caseId}`, CaseSchema)
}

export async function fetchStats(): Promise<Stats> {
  return get('/metrics', StatsSchema)
}

export async function approveEscalation(caseId: string): Promise<void> {
  await request(`/cases/${caseId}/approve`, { method: 'POST' })
}

export async function closeCase(caseId: string): Promise<void> {
  await request(`/cases/${caseId}/close`, { method: 'POST' })
}

export async function simulateFire(payload: any): Promise<{ id: string }> {
  return request<{ id: string }>('/fake-event', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function simulateAction(payload: any): Promise<any> {
  return request('/fake-action', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function clearAllCases(): Promise<void> {
  await request('/cases/clear', { method: 'DELETE' })
}

// ---------- Agent Lab: recovery policy ----------

export interface PolicyScoreRequest {
  case_id?: string
  currency?: string
  amount_due?: number
  days_past_due?: number
  failure_code?: string | null
  failure_class?: 'soft' | 'hard' | 'transient' | 'unknown'
  payment_method_type?: string | null
  method_age_days?: number | null
  attempt_count?: number
  contact_count_7d?: number
  last_contact_hours?: number | null
  prior_successful_payments?: number
  prior_failed_payments?: number
  prior_recoveries?: number
  tenure_days?: number
  segment?: string
  dispute_open?: boolean
  opt_out?: boolean
  hour_local?: number
  weekday?: number
  days_to_month_end?: number
  payday_signal?: boolean
  invoice_age_days?: number | null
}

export interface PolicyAlternative {
  p_pay: number
  amount_if_paid: number
  expected_recovered: number
  expected_cost: number
  expected_net: number
}

export interface PolicyScoreResponse {
  case_id: string
  proposed_action: string
  approved_action: string
  guardrail: string
  p_pay: number | null
  expected_recovered: number | null
  expected_cost: number | null
  expected_net: number | null
  alternatives: Record<string, PolicyAlternative>
  explanation: string[]
  policy_version: string
  model_version: string
  exploration: boolean
  observation: Record<string, unknown>
}

export interface PolicyModelInfo {
  loaded: boolean
  policy_version: string
  model_version: string
  trained_at?: string
  training_rows?: number
  dataset_hash?: string
  exploration?: number
  metrics?: Record<string, unknown>
  play_rates?: Record<string, unknown>
}

export interface EvaluationReport {
  generated?: string
  dataset_hash?: string
  policy?: string
  [key: string]: unknown
}

export async function scorePolicy(payload: PolicyScoreRequest): Promise<PolicyScoreResponse> {
  return request<PolicyScoreResponse>('/policy/score', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function getPolicyModel(): Promise<PolicyModelInfo> {
  return request<PolicyModelInfo>('/policy/model')
}

export async function getPolicyEvaluation(): Promise<EvaluationReport> {
  return request<EvaluationReport>('/policy/evaluation')
}