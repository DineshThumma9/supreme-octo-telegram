import { useEffect, useState } from 'react'
import {
  getLearningStats,
  runSandboxExperiment,
  resetSandboxExperiment,
  getRetrainStatus,
  type LearningStats,
  type RetrainStatus,
} from '../api'

const PLAY_LABELS: Record<string, string> = {
  email_link: 'Email payment link',
  sms_link: 'SMS payment link',
  paypal_invoice_reminder: 'PayPal invoice reminder',
  retry_now: 'Retry now',
  retry_payday: 'Retry at payday',
  update_method_link: 'Update payment method',
  discount_link: 'Discount offer link',
  no_contact: 'No contact (control)',
  human_escalation: 'Escalate to agent',
}

export function LearningPanel() {
  const [provenance, setProvenance] = useState<'live' | 'sandbox'>('live')
  const [stats, setStats] = useState<LearningStats | null>(null)
  const [retrain, setRetrain] = useState<RetrainStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [actionMsg, setActionMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadData = async (targetProv: 'live' | 'sandbox') => {
    setLoading(true)
    setError(null)
    try {
      const [s, r] = await Promise.all([
        getLearningStats(targetProv, targetProv === 'sandbox' ? 'experiment' : 'outcome'),
        getRetrainStatus(),
      ])
      setStats(s)
      setRetrain(r)
    } catch (err: any) {
      setError(err?.message || 'Failed to load learning data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData(provenance)
  }, [provenance])

  const handleRunExperiment = async () => {
    setActionMsg('Generating sandbox experiment...')
    setError(null)
    try {
      await runSandboxExperiment({
        experiment_id: 'demo-v1',
        seed: 42,
        samples_per_play: 60,
        reset: true,
      })
      setActionMsg('Generated 420 sandbox experiment samples.')
      setProvenance('sandbox')
      await loadData('sandbox')
    } catch (err: any) {
      setError(err?.message || 'Failed to generate experiment')
    }
  }

  const handleResetSandbox = async () => {
    setActionMsg('Resetting sandbox...')
    setError(null)
    try {
      const res = await resetSandboxExperiment()
      setActionMsg(`Reset complete (${res.deleted ?? 0} samples removed).`)
      await loadData(provenance)
    } catch (err: any) {
      setError(err?.message || 'Failed to reset sandbox')
    }
  }

  const pct = (num: number | undefined | null) =>
    num !== undefined && num !== null ? `${(num * 100).toFixed(1)}%` : '—'

  return (
    <div className="rounded-lg border border-hairline bg-card p-4 space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-[#3e9b4f]" />
            <h2 className="text-xs font-medium text-primary">Learning loop</h2>
          </div>
          <p className="text-xs text-muted mt-0.5">
            Empirical Bayes over observed attempt outcomes. Live policy uses live outcomes only.
          </p>
        </div>

        {/* View toggle */}
        <div className="inline-flex rounded border border-hairline bg-background p-0.5 self-start sm:self-auto text-xs">
          <button
            type="button"
            onClick={() => setProvenance('live')}
            className={`px-3 py-1 rounded transition-colors ${
              provenance === 'live'
                ? 'bg-raised text-primary font-medium shadow-sm'
                : 'text-muted hover:text-secondary'
            }`}
          >
            Live outcomes
          </button>
          <button
            type="button"
            onClick={() => setProvenance('sandbox')}
            className={`px-3 py-1 rounded transition-colors ${
              provenance === 'sandbox'
                ? 'bg-raised text-primary font-medium shadow-sm'
                : 'text-muted hover:text-secondary'
            }`}
          >
            Sandbox experiment
          </button>
        </div>
      </div>

      {/* Amber banner for sandbox */}
      {provenance === 'sandbox' && (
        <div className="p-2.5 rounded bg-raised text-xs text-[#f5a623] border border-[#f5a623]/20 flex items-center justify-between gap-2">
          <span>Sandbox experiment — simulated outcomes, not live performance.</span>
          <span className="text-[11px] font-mono opacity-80">demo-v1</span>
        </div>
      )}

      {error && (
        <div className="p-2.5 rounded bg-raised text-xs text-[#e5484d] border border-[#e5484d]/20">
          {error}
        </div>
      )}

      {actionMsg && !error && (
        <div className="p-2.5 rounded bg-raised text-xs text-[#3e9b4f] border border-[#3e9b4f]/20">
          {actionMsg}
        </div>
      )}

      {/* Stats Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs text-left border-collapse">
          <thead>
            <tr className="border-b border-hairline text-muted">
              <th className="py-2 px-3 font-normal">Play</th>
              <th className="py-2 px-3 font-normal text-right">Prior p</th>
              <th className="py-2 px-3 font-normal text-right">n</th>
              <th className="py-2 px-3 font-normal text-right">Recovered</th>
              <th className="py-2 px-3 font-normal text-right">Timeouts</th>
              <th className="py-2 px-3 font-normal text-right">Posterior p</th>
              <th className="py-2 px-3 font-normal text-right">EB Weight</th>
            </tr>
          </thead>
          <tbody>
            {stats && stats.plays.length > 0 ? (
              stats.plays.map((row) => (
                <tr key={row.play} className="border-b border-hairline hover:bg-raised/50">
                  <td className="py-2.5 px-3 text-secondary">
                    {PLAY_LABELS[row.play] || row.play}
                  </td>
                  <td className="py-2.5 px-3 text-right font-mono tabular text-muted">
                    {pct(row.prior_p)}
                  </td>
                  <td className="py-2.5 px-3 text-right font-mono tabular text-secondary">
                    {row.n}
                  </td>
                  <td className="py-2.5 px-3 text-right font-mono tabular text-[#3e9b4f]">
                    {row.k}
                  </td>
                  <td className="py-2.5 px-3 text-right font-mono tabular text-muted">
                    {row.timeouts}
                  </td>
                  <td className="py-2.5 px-3 text-right font-mono tabular text-primary font-medium">
                    {row.n > 0 ? pct(row.posterior_p) : <span className="text-muted italic">prior only</span>}
                  </td>
                  <td className="py-2.5 px-3 text-right font-mono tabular text-secondary">
                    {row.weight > 0 ? row.weight.toFixed(3) : '0.000'}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={7} className="py-4 text-center text-muted italic">
                  {loading ? 'Loading stats...' : 'No learning samples recorded yet. (Model prior active)'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Action buttons & retrain status line */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-1 border-t border-hairline">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRunExperiment}
            className="px-3 py-1.5 rounded bg-raised hover:bg-hover text-xs text-secondary transition-colors"
          >
            Run sandbox experiment
          </button>
          <button
            type="button"
            onClick={handleResetSandbox}
            className="px-3 py-1.5 rounded bg-raised hover:bg-hover text-xs text-muted hover:text-secondary transition-colors"
          >
            Reset sandbox
          </button>
        </div>

        <div className="text-[11px] text-muted font-mono">
          Retrain:{' '}
          <span className={retrain?.enabled ? 'text-[#3e9b4f]' : 'text-muted'}>
            {retrain?.enabled ? 'enabled' : 'disabled'}
          </span>{' '}
          ·{' '}
          <span className="text-secondary tabular">
            {retrain?.counts?.samples ?? 0}/{retrain?.thresholds?.samples ?? 100} live samples
          </span>{' '}
          · auto-promote off
        </div>
      </div>
    </div>
  )
}
