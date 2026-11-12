import { useEffect, useState } from 'react'
import {
  scorePolicy,
  getPolicyModel,
  getPolicyEvaluation,
  type PolicyScoreRequest,
  type PolicyScoreResponse,
} from '../api'
import { fmt } from '../utils/formatters'
import { LearningPanel } from './LearningPanel'

const PLAY_LABELS: Record<string, string> = {
  no_contact: 'No contact (control)',
  email_link: 'Email payment link',
  sms_link: 'SMS payment link',
  paypal_invoice_reminder: 'PayPal invoice reminder',
  retry_now: 'Retry now',
  retry_payday: 'Retry at payday',
  update_method_link: 'Update payment method',
  discount_link: 'Discount offer link',
  human_escalation: 'Escalate to agent',
}

function formatFeatureAttribution(raw: string): { label: string; impact: string; isPositive: boolean } {
  // Parses patterns like: "amount_due=480.0 (-58.89)" or "method_age_days (+21.02)"
  const match = raw.match(/^([a-z_]+)(?:=([^(\s]+))?\s*\(([-+]?[0-9.]+)\)$/i)
  if (!match) {
    return { label: raw, impact: '', isPositive: false }
  }

  const [, key, val, impactNum] = match
  const impactVal = parseFloat(impactNum)
  const isPositive = impactVal >= 0
  const impactFormatted = `${isPositive ? '+' : ''}$${Math.abs(impactVal).toFixed(2)}`

  const niceKeyMap: Record<string, string> = {
    amount_due: 'Amount due',
    days_past_due: 'Days past due',
    segment: 'Customer segment',
    method_age_days: 'Payment method age',
    failure_class: 'Failure class',
    attempt_count: 'Retry attempt',
    tenure_days: 'Account tenure',
    prior_recoveries: 'Prior recoveries',
    payday_signal: 'Payday signal',
    contact_count_7d: 'Contacts in 7d',
  }

  const labelPrefix = niceKeyMap[key] || key.replace(/_/g, ' ')
  let valDisplay = val ? String(val) : ''
  if (key === 'amount_due' && val) valDisplay = `$${parseFloat(val).toFixed(0)}`
  if (key === 'method_age_days' && val) valDisplay = `${val}d`
  if (key === 'tenure_days' && val) valDisplay = `${val}d`

  const label = valDisplay ? `${labelPrefix} (${valDisplay})` : labelPrefix
  return { label, impact: impactFormatted, isPositive }
}

export function AgentLab() {
  const [model, setModel] = useState<any>(null)
  const [modelError, setModelError] = useState<string | null>(null)
  const [evaluation, setEvaluation] = useState<any>(null)
  const [evalError, setEvalError] = useState<string | null>(null)

  const [scoring, setScoring] = useState(false)
  const [scoreResult, setScoreResult] = useState<PolicyScoreResponse | null>(null)
  const [scoreError, setScoreError] = useState<string | null>(null)
  const [useSandboxLearning, setUseSandboxLearning] = useState(false)

  const defaultForm: PolicyScoreRequest = {
    currency: 'USD',
    amount_due: 480,
    days_past_due: 5,
    failure_code: 'INSUFFICIENT_FUNDS',
    failure_class: 'soft',
    payment_method_type: 'card',
    method_age_days: 180,
    attempt_count: 1,
    contact_count_7d: 0,
    last_contact_hours: null,
    prior_successful_payments: 4,
    prior_failed_payments: 1,
    prior_recoveries: 1,
    tenure_days: 180,
    segment: 'card',
    dispute_open: false,
    opt_out: false,
    hour_local: 14,
    weekday: 2,
    days_to_month_end: 12,
    payday_signal: false,
    invoice_age_days: null,
  }

  const [form, setForm] = useState<PolicyScoreRequest>(defaultForm)

  useEffect(() => {
    Promise.allSettled([
      getPolicyModel().then((m) => setModel(m)).catch((e) => setModelError(String(e))),
      getPolicyEvaluation().then((e) => setEvaluation(e)).catch((e) => setEvalError(String(e))),
    ])
  }, [])

  const applyPreset = (presetName: string) => {
    if (presetName === 'soft_decline') {
      setForm({
        ...defaultForm,
        amount_due: 480,
        days_past_due: 3,
        failure_class: 'soft',
        segment: 'card',
        payday_signal: false,
        dispute_open: false,
        opt_out: false,
      })
    } else if (presetName === 'b2b_invoice') {
      setForm({
        ...defaultForm,
        amount_due: 1250,
        days_past_due: 14,
        failure_class: 'soft',
        segment: 'b2b',
        attempt_count: 2,
        payday_signal: false,
        dispute_open: false,
        opt_out: false,
      })
    } else if (presetName === 'payday_due') {
      setForm({
        ...defaultForm,
        amount_due: 350,
        days_past_due: 4,
        failure_class: 'soft',
        segment: 'card',
        payday_signal: true,
        dispute_open: false,
        opt_out: false,
      })
    } else if (presetName === 'dispute_guardrail') {
      setForm({
        ...defaultForm,
        amount_due: 500,
        days_past_due: 20,
        failure_class: 'hard',
        segment: 'card',
        dispute_open: true,
        opt_out: false,
      })
    }
  }

  const handleScore = async (e: React.FormEvent) => {
    e.preventDefault()
    setScoring(true)
    setScoreError(null)
    setScoreResult(null)
    try {
      const payload: PolicyScoreRequest = {
        ...form,
        amount_due: Number(form.amount_due) || 480,
        days_past_due: Number(form.days_past_due) || 0,
        attempt_count: Number(form.attempt_count) || 0,
        method_age_days: Number(form.method_age_days) || 0,
        learning_provenance: useSandboxLearning ? 'sandbox' : 'live',
      }
      const result = await scorePolicy(payload)
      setScoreResult(result)
    } catch (err: any) {
      setScoreError(err?.message || 'Policy scoring failed')
    } finally {
      setScoring(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* 0. Online learning loop */}
      <LearningPanel />

      {/* 1. Served policy diagnostics */}
      <div className="rounded-lg border border-hairline bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className={`w-1.5 h-1.5 rounded-full ${model?.loaded ? 'bg-[#4cc38a]' : 'bg-[#85858b]'}`} />
            <h2 className="text-xs font-medium text-primary">
              {model?.loaded ? 'Production model active' : 'Baseline rules active'}
            </h2>
          </div>
          <span className="text-[11px] text-muted tabular">
            Policy {String(model?.policy_version ?? 'rules-v0')} · Model {String(model?.model_version ?? 'none')}
          </span>
        </div>

        {modelError && (
          <div className="mb-3 p-2.5 rounded bg-raised text-xs text-[#e5484d]">
            {modelError}
          </div>
        )}

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          <div className="p-2.5 rounded bg-raised">
            <div className="text-muted text-[11px] mb-1">Training episodes</div>
            <div className="text-primary font-medium tabular">
              {model?.training_rows ? fmt(model.training_rows) : '—'}
            </div>
          </div>
          <div className="p-2.5 rounded bg-raised">
            <div className="text-muted text-[11px] mb-1">AUROC (discrimination)</div>
            <div className="text-primary font-medium tabular">
              {model?.metrics?.auroc ? Number(model.metrics.auroc).toFixed(3) : '—'}
            </div>
          </div>
          <div className="p-2.5 rounded bg-raised">
            <div className="text-muted text-[11px] mb-1">AUPRC (precision)</div>
            <div className="text-primary font-medium tabular">
              {model?.metrics?.auprc ? Number(model.metrics.auprc).toFixed(3) : '—'}
            </div>
          </div>
          <div className="p-2.5 rounded bg-raised">
            <div className="text-muted text-[11px] mb-1">Brier score</div>
            <div className="text-primary font-medium tabular">
              {model?.metrics?.brier ? Number(model.metrics.brier).toFixed(3) : '—'}
            </div>
          </div>
        </div>
      </div>

      {/* 2. Interactive policy scoring */}
      <div className="rounded-lg border border-hairline bg-card p-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
          <div>
            <h2 className="text-xs font-medium text-primary">Live policy score</h2>
            <p className="text-xs text-muted mt-0.5">
              Evaluates eligible plays and applies deterministic guardrails.
            </p>
          </div>

          {/* Quick presets */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] text-muted mr-1">Presets:</span>
            <button
              type="button"
              onClick={() => applyPreset('soft_decline')}
              className="h-6 px-2 rounded bg-raised hover:bg-hover text-[11px] text-secondary hover:text-primary transition-colors"
            >
              Soft decline
            </button>
            <button
              type="button"
              onClick={() => applyPreset('b2b_invoice')}
              className="h-6 px-2 rounded bg-raised hover:bg-hover text-[11px] text-secondary hover:text-primary transition-colors"
            >
              B2B invoice
            </button>
            <button
              type="button"
              onClick={() => applyPreset('payday_due')}
              className="h-6 px-2 rounded bg-raised hover:bg-hover text-[11px] text-secondary hover:text-primary transition-colors"
            >
              Payday signal
            </button>
            <button
              type="button"
              onClick={() => applyPreset('dispute_guardrail')}
              className="h-6 px-2 rounded bg-raised hover:bg-hover text-[11px] text-secondary hover:text-primary transition-colors"
            >
              Dispute open
            </button>
          </div>
        </div>

        <form onSubmit={handleScore} className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 text-xs">
            {/* Amount Due */}
            <div>
              <label className="block text-muted text-[11px] mb-1">Amount due (USD)</label>
              <input
                type="number"
                value={form.amount_due === 0 ? '' : (form.amount_due ?? '')}
                onChange={(e) => setForm({ ...form, amount_due: e.target.value === '' ? ('' as any) : Number(e.target.value) })}
                className="w-full h-8 px-2.5 rounded bg-raised border border-hairline text-xs text-primary tabular focus:border-focus focus:outline-none"
              />
            </div>

            {/* Days past due */}
            <div>
              <label className="block text-muted text-[11px] mb-1">Days past due</label>
              <input
                type="number"
                value={form.days_past_due ?? ''}
                onChange={(e) => setForm({ ...form, days_past_due: Number(e.target.value) })}
                className="w-full h-8 px-2.5 rounded bg-raised border border-hairline text-xs text-primary tabular focus:border-focus focus:outline-none"
              />
            </div>

            {/* Failure class */}
            <div>
              <label className="block text-muted text-[11px] mb-1">Failure class</label>
              <select
                value={form.failure_class}
                onChange={(e) => setForm({ ...form, failure_class: e.target.value as any })}
                className="w-full h-8 px-2 rounded bg-raised border border-hairline text-xs text-primary focus:border-focus focus:outline-none"
              >
                <option value="soft">Soft decline</option>
                <option value="hard">Hard decline</option>
                <option value="transient">Transient</option>
                <option value="unknown">Unknown</option>
              </select>
            </div>

            {/* Segment */}
            <div>
              <label className="block text-muted text-[11px] mb-1">Customer segment</label>
              <select
                value={form.segment}
                onChange={(e) => setForm({ ...form, segment: e.target.value })}
                className="w-full h-8 px-2 rounded bg-raised border border-hairline text-xs text-primary focus:border-focus focus:outline-none"
              >
                <option value="card">Consumer card</option>
                <option value="b2b">B2B commercial</option>
                <option value="paypal">PayPal</option>
              </select>
            </div>

            {/* Attempt count */}
            <div>
              <label className="block text-muted text-[11px] mb-1">Attempt count</label>
              <input
                type="number"
                value={form.attempt_count ?? ''}
                onChange={(e) => setForm({ ...form, attempt_count: Number(e.target.value) })}
                className="w-full h-8 px-2.5 rounded bg-raised border border-hairline text-xs text-primary tabular focus:border-focus focus:outline-none"
              />
            </div>

            {/* Payday signal */}
            <div>
              <label className="block text-muted text-[11px] mb-1">Payday signal</label>
              <select
                value={String(form.payday_signal)}
                onChange={(e) => setForm({ ...form, payday_signal: e.target.value === 'true' })}
                className="w-full h-8 px-2 rounded bg-raised border border-hairline text-xs text-primary focus:border-focus focus:outline-none"
              >
                <option value="false">No</option>
                <option value="true">Yes (imminent)</option>
              </select>
            </div>

            {/* Dispute open */}
            <div>
              <label className="block text-muted text-[11px] mb-1">Dispute open</label>
              <select
                value={String(form.dispute_open)}
                onChange={(e) => setForm({ ...form, dispute_open: e.target.value === 'true' })}
                className="w-full h-8 px-2 rounded bg-raised border border-hairline text-xs text-primary focus:border-focus focus:outline-none"
              >
                <option value="false">No</option>
                <option value="true">Yes (guardrail block)</option>
              </select>
            </div>

            {/* Opt out */}
            <div>
              <label className="block text-muted text-[11px] mb-1">Opted out</label>
              <select
                value={String(form.opt_out)}
                onChange={(e) => setForm({ ...form, opt_out: e.target.value === 'true' })}
                className="w-full h-8 px-2 rounded bg-raised border border-hairline text-xs text-primary focus:border-focus focus:outline-none"
              >
                <option value="false">No</option>
                <option value="true">Yes</option>
              </select>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 pt-1">
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-muted">
                Select play with maximum expected recovery net of channel cost.
              </span>
              <label className="flex items-center gap-1.5 text-xs text-secondary cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={useSandboxLearning}
                  onChange={(e) => setUseSandboxLearning(e.target.checked)}
                  className="rounded border-hairline bg-raised text-primary focus:ring-0"
                />
                <span className={useSandboxLearning ? 'text-[#f5a623] font-medium' : 'text-muted'}>
                  Sandbox learning (simulated)
                </span>
              </label>
            </div>
            <button
              type="submit"
              disabled={scoring}
              className="h-8 px-4 rounded bg-[#ededed] text-[#141415] hover:bg-white text-xs font-medium transition-colors disabled:opacity-50"
            >
              {scoring ? 'Scoring…' : 'Score policy'}
            </button>
          </div>
        </form>

        {scoreError && (
          <div className="mt-3 p-2.5 rounded bg-raised text-xs text-[#e5484d]">
            {scoreError}
          </div>
        )}

        {/* Score Result View */}
        {scoreResult && (
          <div className="mt-4 pt-4 border-t border-hairline space-y-4">
            {/* Header decision */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded bg-raised">
              <div className="flex items-center gap-2 text-xs">
                <span className="text-muted">Proposed:</span>
                <span className="text-secondary font-medium">{PLAY_LABELS[scoreResult.proposed_action] ?? scoreResult.proposed_action}</span>
                <span className="text-muted mx-1">→</span>
                <span className="text-muted">Approved:</span>
                <span className="text-primary font-medium">{PLAY_LABELS[scoreResult.approved_action] ?? scoreResult.approved_action}</span>
              </div>
              <div className="text-[11px] text-muted">
                Guardrail:{' '}
                <span className={scoreResult.guardrail.includes('block') ? 'text-[#e5484d]' : 'text-primary'}>
                  {scoreResult.guardrail}
                </span>
              </div>
            </div>

            {/* Expected Values */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              <div className="p-3 rounded border border-hairline bg-page">
                <div className="text-muted text-[11px] mb-1">P(pay)</div>
                <div className="text-primary font-medium tabular text-sm">
                  {scoreResult.p_pay != null ? `${(scoreResult.p_pay * 100).toFixed(1)}%` : '—'}
                </div>
              </div>
              <div className="p-3 rounded border border-hairline bg-page">
                <div className="text-muted text-[11px] mb-1">Expected recovered</div>
                <div className="text-primary font-medium tabular text-sm">
                  ${scoreResult.expected_recovered != null ? Number(scoreResult.expected_recovered).toFixed(2) : '—'}
                </div>
              </div>
              <div className="p-3 rounded border border-hairline bg-page">
                <div className="text-muted text-[11px] mb-1">Expected cost</div>
                <div className="text-primary font-medium tabular text-sm">
                  ${scoreResult.expected_cost != null ? Number(scoreResult.expected_cost).toFixed(2) : '—'}
                </div>
              </div>
              <div className="p-3 rounded border border-hairline bg-page">
                <div className="text-muted text-[11px] mb-1">Expected net</div>
                <div className="text-[#4cc38a] font-medium tabular text-sm">
                  ${scoreResult.expected_net != null ? Number(scoreResult.expected_net).toFixed(2) : '—'}
                </div>
              </div>
            </div>

            {/* Alternatives */}
            {scoreResult.alternatives && (
              <div>
                <div className="text-xs text-muted mb-2">Evaluated alternatives</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                  {Object.entries(scoreResult.alternatives).map(([play, alt]: [string, any]) => {
                    const isApproved = play === scoreResult.approved_action
                    return (
                      <div
                        key={play}
                        className={`p-2.5 rounded border text-xs transition-colors ${
                          isApproved
                            ? 'border-hairline bg-raised'
                            : 'border-hairline/50 bg-page opacity-75'
                        }`}
                      >
                        <div className="font-medium text-primary truncate mb-1">
                          {PLAY_LABELS[play] ?? play}
                        </div>
                        <div className="flex items-center justify-between text-[11px] text-muted tabular">
                          <span>p={(alt.p_pay * 100).toFixed(1)}%</span>
                          <span className={isApproved ? 'text-primary font-medium' : 'text-secondary'}>
                            net ${Number(alt.expected_net).toFixed(2)}
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Feature attribution (Why this play) */}
            {scoreResult.explanation && scoreResult.explanation.length > 0 && (
              <div>
                <div className="text-xs text-muted mb-2">Decision factors</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {scoreResult.explanation.map((rawExp: string, i: number) => {
                    const parsed = formatFeatureAttribution(rawExp)
                    return (
                      <div
                        key={i}
                        className="p-2 rounded bg-raised border border-hairline flex items-center justify-between text-xs"
                      >
                        <span className="text-secondary truncate">{parsed.label}</span>
                        {parsed.impact && (
                          <span
                            className={`tabular font-medium text-[11px] ml-2 shrink-0 ${
                              parsed.isPositive ? 'text-[#4cc38a]' : 'text-[#e5484d]'
                            }`}
                          >
                            {parsed.impact}
                          </span>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 3. Offline evaluation benchmark */}
      <div className="rounded-lg border border-hairline bg-card p-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-xs font-medium text-primary">Offline evaluation (simulated)</h2>
          {evaluation?.dataset?.dataset_hash && (
            <span className="text-[11px] text-muted font-mono tabular">
              hash {evaluation.dataset.dataset_hash.slice(0, 8)}
            </span>
          )}
        </div>
        <p className="text-xs text-muted mb-3">
          Calibrated synthetic simulator with potential outcomes.
        </p>

        {evalError && (
          <div className="mb-3 p-2.5 rounded bg-raised text-xs text-[#e5484d]">
            {evalError}
          </div>
        )}

        {evaluation?.policies ? (
          <div className="space-y-3">
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="border-b border-hairline text-muted">
                    <th className="py-2 px-3 font-normal">Policy</th>
                    <th className="py-2 px-3 font-normal text-right">Net / 1,000</th>
                    <th className="py-2 px-3 font-normal text-right">Recovery rate</th>
                    <th className="py-2 px-3 font-normal text-right">Cost / recovery</th>
                    <th className="py-2 px-3 font-normal text-right">Opt-out</th>
                    <th className="py-2 px-3 font-normal text-right">Dispute</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { key: 'no_contact', label: 'No contact (control)' },
                    { key: 'rules', label: 'Rules baseline' },
                    { key: 'ml_ev', label: 'ML expected-value (active)' },
                    { key: 'oracle', label: 'Oracle (upper bound)' },
                  ].map(({ key, label }) => {
                    const row = evaluation.policies[key]
                    if (!row) return null
                    const isML = key === 'ml_ev'

                    return (
                      <tr
                        key={key}
                        className={`border-b border-hairline ${isML ? 'bg-raised font-medium' : ''}`}
                      >
                        <td className="py-2.5 px-3">
                          <span className={isML ? 'text-primary' : 'text-secondary'}>{label}</span>
                        </td>
                        <td className="py-2.5 px-3 text-right tabular text-secondary">
                          ${fmt(row.net_per_1000)}
                        </td>
                        <td className="py-2.5 px-3 text-right tabular text-secondary">
                          {Number(row.recovery_rate_pct).toFixed(1)}%
                        </td>
                        <td className="py-2.5 px-3 text-right tabular text-secondary">
                          ${Number(row.cost_per_recovery).toFixed(2)}
                        </td>
                        <td className="py-2.5 px-3 text-right tabular text-muted">
                          {Number(row.opt_out_pct).toFixed(2)}%
                        </td>
                        <td className="py-2.5 px-3 text-right tabular text-muted">
                          {Number(row.dispute_pct).toFixed(2)}%
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {evaluation.lift && (
              <div className="p-3 rounded bg-raised text-xs text-muted flex flex-wrap items-center justify-between gap-2">
                <span>
                  ML vs rules lift:{' '}
                  <strong className="text-primary font-medium tabular">
                    +${Number(evaluation.lift.ml_vs_rules_per_1000).toFixed(2)}
                  </strong>{' '}
                  per 1,000 cases
                </span>
                <span>
                  Oracle gap closed:{' '}
                  <strong className="text-primary font-medium tabular">
                    {Number(evaluation.lift.oracle_gap_closed_pct).toFixed(2)}%
                  </strong>
                </span>
              </div>
            )}
          </div>
        ) : (
          <div className="text-xs text-muted italic py-4">
            No evaluation data available.
          </div>
        )}
      </div>
    </div>
  )
}
