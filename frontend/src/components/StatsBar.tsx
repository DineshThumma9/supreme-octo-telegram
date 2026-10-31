
import type { Stats } from '../types'
import { DEFAULT_STATS } from '../store/useCaseStore'
import { fmt } from '../utils/formatters'

export function StatsBar({ stats }: { stats?: Stats | null; loading?: boolean }) {
  const currentStats = stats || DEFAULT_STATS

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 w-full mb-8">
      {/* At Risk */}
      <div className="bg-[#0f0f14] border border-zinc-800/60 rounded-xl p-5 flex flex-col justify-center">
        <p className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-2">At Risk</p>
        <p className="text-3xl font-bold text-amber-400">${fmt(currentStats.total_at_risk)}</p>
      </div>

      {/* Recovered */}
      <div className="bg-[#0f0f14] border border-zinc-800/60 rounded-xl p-5 flex flex-col justify-center">
        <p className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-2">Recovered</p>
        <p className="text-3xl font-bold text-emerald-400">${fmt(currentStats.recovered_amount)}</p>
      </div>

      {/* Recovery Rate */}
      <div className="bg-[#0f0f14] border border-zinc-800/60 rounded-xl p-5 flex flex-col justify-center">
        <p className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-2">Recovery Rate</p>
        <p className="text-3xl font-bold text-violet-400">{currentStats.recovery_rate_pct}%</p>
      </div>

      {/* Total Cases */}
      <div className="bg-[#0f0f14] border border-zinc-800/60 rounded-xl p-5 flex flex-col justify-center">
        <p className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-2">Total Cases</p>
        <p className="text-3xl font-bold text-zinc-100">{currentStats.total_cases}</p>
      </div>
    </div>
  )
}
