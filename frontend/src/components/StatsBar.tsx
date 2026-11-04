
import type { Stats } from '../types'
import { DEFAULT_STATS } from '../store/useCaseStore'
import { fmt } from '../utils/formatters'

export function StatsBar({ stats }: { stats?: Stats | null; loading?: boolean }) {
  const currentStats = stats || DEFAULT_STATS

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 w-full mb-8">
      {/* At Risk — Signature Moment: calm neutral card with subtle amber indicator */}
      <div className="bg-[#18181b] border border-zinc-800 rounded-lg p-4 flex flex-col justify-between relative overflow-hidden">
        <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-amber-500/80" />
        <p className="text-xs text-zinc-400 mb-2">At risk</p>
        <p className="text-2xl font-medium tracking-tight text-zinc-100 tabular">
          ${fmt(currentStats.total_at_risk)}
        </p>
      </div>

      {/* Recovered */}
      <div className="bg-[#18181b] border border-zinc-800 rounded-lg p-4 flex flex-col justify-between">
        <p className="text-xs text-zinc-400 mb-2">Recovered</p>
        <p className="text-2xl font-medium tracking-tight text-zinc-100 tabular">
          ${fmt(currentStats.recovered_amount)}
        </p>
      </div>

      {/* Recovery Rate — The leading figure */}
      <div className="bg-[#18181b] border border-zinc-800 rounded-lg p-4 flex flex-col justify-between">
        <p className="text-xs text-zinc-400 mb-2">Recovery rate</p>
        <p className="text-2xl font-medium tracking-tight text-amber-500 tabular">
          {currentStats.recovery_rate_pct}%
        </p>
      </div>

      {/* Total Cases */}
      <div className="bg-[#18181b] border border-zinc-800 rounded-lg p-4 flex flex-col justify-between">
        <p className="text-xs text-zinc-400 mb-2">Total cases</p>
        <p className="text-2xl font-medium tracking-tight text-zinc-100 tabular">
          {currentStats.total_cases}
        </p>
      </div>
    </div>
  )
}
