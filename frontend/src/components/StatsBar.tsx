import type { Stats } from '../types'
import { DEFAULT_STATS } from '../store/useCaseStore'
import { fmt } from '../utils/formatters'

interface StatsBarProps {
  stats?: Stats | null
  loading?: boolean
  onReviewEscalated?: () => void
}

export function StatsBar({ stats, loading = false, onReviewEscalated }: StatsBarProps) {
  const currentStats = stats || DEFAULT_STATS

  return (
    <div className="space-y-3 mb-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {/* Metric 1 */}
        <div className="rounded-lg border border-hairline bg-card p-4">
          <div className="text-xs text-muted mb-2">Recovery rate</div>
          <div className="text-2xl font-medium text-primary tabular tracking-tight">
            {loading ? '—' : `${currentStats.recovery_rate_pct.toFixed(0)}%`}
          </div>
          <div className="text-xs text-muted mt-1 tabular">
            {currentStats.recovered_count} of {currentStats.total_cases} cases
          </div>
        </div>

        {/* Metric 2 */}
        <div className="rounded-lg border border-hairline bg-card p-4">
          <div className="text-xs text-muted mb-2">Amount at risk</div>
          <div className="text-2xl font-medium text-primary tabular tracking-tight">
            {loading ? '—' : `$${fmt(currentStats.total_at_risk)}`}
          </div>
          <div className="text-xs text-muted mt-1">
            Active unrecovered exposure
          </div>
        </div>

        {/* Metric 3 */}
        <div className="rounded-lg border border-hairline bg-card p-4">
          <div className="text-xs text-muted mb-2">Recovered</div>
          <div className="text-2xl font-medium text-primary tabular tracking-tight">
            {loading ? '—' : `$${fmt(currentStats.recovered_amount)}`}
          </div>
          <div className="text-xs text-muted mt-1">
            From automated retries & links
          </div>
        </div>

        {/* Metric 4 */}
        <div className="rounded-lg border border-hairline bg-card p-4">
          <div className="text-xs text-muted mb-2">Total cases</div>
          <div className="text-2xl font-medium text-primary tabular tracking-tight">
            {loading ? '—' : currentStats.total_cases}
          </div>
          <div className="text-xs text-muted mt-1 tabular">
            {currentStats.still_active ?? 0} active in queue
          </div>
        </div>
      </div>

      {/* Escalation Attention Bar */}
      {currentStats.escalated_count > 0 && (
        <div className="rounded-lg border border-hairline bg-raised px-4 py-2.5 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-[#e5484d] shrink-0" />
            <span className="text-primary font-medium">
              {currentStats.escalated_count} cases need human approval
            </span>
            <span className="text-muted hidden sm:inline">
              · Automated plays paused pending review
            </span>
          </div>
          {onReviewEscalated && (
            <button
              onClick={onReviewEscalated}
              className="text-xs text-secondary hover:text-primary transition-colors underline underline-offset-4"
            >
              Review cases
            </button>
          )}
        </div>
      )}
    </div>
  )
}
