import { useState, useMemo } from 'react'
import type { Case } from '../types'
import { fmt, fmtTs } from '../utils/formatters'
import { TypeBadge } from './TypeBadge'
import { StatusPill } from './StatusPill'
import { ChannelChip } from './ChannelChip'
import { Search, ChevronRight } from 'lucide-react'

interface CaseTableProps {
  cases: Case[]
  loading: boolean
  onRowClick: (id: string) => void
  showFilterTabs?: boolean
  defaultStatusFilter?: string
}

export function CaseTable({
  cases,
  loading,
  onRowClick,
  showFilterTabs = true,
  defaultStatusFilter = 'all',
}: CaseTableProps) {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState(defaultStatusFilter)

  const filteredCases = useMemo(() => {
    return cases.filter((c) => {
      // Status filter
      if (statusFilter === 'escalated' && c.recovery_status !== 'escalated') return false
      if (statusFilter === 'active' && ['escalated', 'recovered', 'closed'].includes(c.recovery_status)) return false
      if (statusFilter === 'recovered' && c.recovery_status !== 'recovered') return false
      if (statusFilter === 'closed' && c.recovery_status !== 'closed') return false

      // Search filter
      if (!search.trim()) return true
      const q = search.toLowerCase()
      const name = (c.customer?.name || '').toLowerCase()
      const email = (c.customer?.email || '').toLowerCase()
      const caseId = (c.case_id || '').toLowerCase()
      const type = (c.case_type || '').toLowerCase()
      return name.includes(q) || email.includes(q) || caseId.includes(q) || type.includes(q)
    })
  }, [cases, search, statusFilter])

  const counts = useMemo(() => {
    return {
      all: cases.length,
      escalated: cases.filter((c) => c.recovery_status === 'escalated').length,
      active: cases.filter((c) => !['escalated', 'recovered', 'closed'].includes(c.recovery_status)).length,
      recovered: cases.filter((c) => c.recovery_status === 'recovered').length,
    }
  }, [cases])

  return (
    <div className="rounded-lg border border-hairline bg-card overflow-hidden">
      {/* Controls Bar */}
      <div className="p-3 border-b border-hairline flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        {/* Status Tabs */}
        {showFilterTabs && (
          <div className="flex items-center gap-1 overflow-x-auto" role="tablist">
            <button
              onClick={() => setStatusFilter('all')}
              className={`h-7 px-2.5 rounded text-xs font-medium transition-colors ${
                statusFilter === 'all'
                  ? 'bg-raised text-primary'
                  : 'text-muted hover:text-secondary'
              }`}
            >
              All <span className="tabular text-muted ml-1">{counts.all}</span>
            </button>
            <button
              onClick={() => setStatusFilter('escalated')}
              className={`h-7 px-2.5 rounded text-xs font-medium transition-colors ${
                statusFilter === 'escalated'
                  ? 'bg-raised text-primary'
                  : 'text-muted hover:text-secondary'
              }`}
            >
              Needs approval <span className={`tabular ml-1 ${counts.escalated > 0 ? 'text-[#e5484d]' : 'text-muted'}`}>{counts.escalated}</span>
            </button>
            <button
              onClick={() => setStatusFilter('active')}
              className={`h-7 px-2.5 rounded text-xs font-medium transition-colors ${
                statusFilter === 'active'
                  ? 'bg-raised text-primary'
                  : 'text-muted hover:text-secondary'
              }`}
            >
              Active <span className="tabular text-muted ml-1">{counts.active}</span>
            </button>
            <button
              onClick={() => setStatusFilter('recovered')}
              className={`h-7 px-2.5 rounded text-xs font-medium transition-colors ${
                statusFilter === 'recovered'
                  ? 'bg-raised text-primary'
                  : 'text-muted hover:text-secondary'
              }`}
            >
              Recovered <span className="tabular text-muted ml-1">{counts.recovered}</span>
            </button>
          </div>
        )}

        {/* Search */}
        <div className="relative w-full sm:w-64">
          <Search className="w-3.5 h-3.5 text-muted absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search cases…"
            className="w-full h-7 pl-8 pr-3 rounded bg-deep border border-hairline text-xs text-primary placeholder:text-muted focus:border-focus focus:outline-none"
          />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="border-b border-hairline text-muted">
              <th className="py-2.5 px-4 font-normal w-12 text-muted tabular">#</th>
              <th className="py-2.5 px-4 font-normal">Customer</th>
              <th className="py-2.5 px-4 font-normal">Status</th>
              <th className="py-2.5 px-4 font-normal text-right">Amount</th>
              <th className="py-2.5 px-4 font-normal">Failure type</th>
              <th className="py-2.5 px-4 font-normal">Channel</th>
              <th className="py-2.5 px-4 font-normal">Next scheduled</th>
              <th className="py-2.5 px-4 font-normal w-10"></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-b border-hairline">
                  <td className="py-3 px-4 text-muted tabular">{i + 1}</td>
                  <td className="py-3 px-4">
                    <div className="w-24 h-3 bg-raised rounded mb-1" />
                    <div className="w-36 h-2.5 bg-raised/50 rounded" />
                  </td>
                  <td className="py-3 px-4"><div className="w-16 h-3 bg-raised rounded" /></td>
                  <td className="py-3 px-4 text-right"><div className="w-12 h-3 bg-raised rounded ml-auto" /></td>
                  <td className="py-3 px-4"><div className="w-20 h-3 bg-raised rounded" /></td>
                  <td className="py-3 px-4"><div className="w-16 h-3 bg-raised rounded" /></td>
                  <td className="py-3 px-4"><div className="w-24 h-3 bg-raised rounded" /></td>
                  <td className="py-3 px-4"></td>
                </tr>
              ))
            ) : filteredCases.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-12 text-center text-muted text-xs">
                  {search ? 'No cases match your search.' : 'No cases in this view.'}
                </td>
              </tr>
            ) : (
              filteredCases.map((c, idx) => (
                <tr
                  key={c.case_id}
                  onClick={() => onRowClick(c.case_id)}
                  className="border-b border-hairline hover:bg-raised/60 transition-colors cursor-pointer group"
                >
                  {/* Number */}
                  <td className="py-3 px-4 text-muted tabular">{idx + 1}</td>

                  {/* Customer */}
                  <td className="py-3 px-4 min-w-[180px]">
                    <div className="font-medium text-primary truncate">{c.customer.name || 'Unknown'}</div>
                    <div className="text-[11px] text-muted truncate mt-0.5">{c.customer.email}</div>
                  </td>

                  {/* Status */}
                  <td className="py-3 px-4">
                    <StatusPill status={c.recovery_status} />
                  </td>

                  {/* Amount */}
                  <td className="py-3 px-4 text-right font-medium tabular text-primary">
                    ${fmt(c.amount)}
                  </td>

                  {/* Type */}
                  <td className="py-3 px-4">
                    <TypeBadge type={c.case_type} />
                  </td>

                  {/* Channel */}
                  <td className="py-3 px-4">
                    <ChannelChip action={c.last_action_taken} />
                  </td>

                  {/* Next Scheduled */}
                  <td className="py-3 px-4 text-muted tabular whitespace-nowrap">
                    {c.next_retry_at ? fmtTs(c.next_retry_at) : '—'}
                  </td>

                  {/* Inspect affordance */}
                  <td className="py-3 px-4 text-right">
                    <ChevronRight className="w-3.5 h-3.5 text-muted group-hover:text-primary transition-colors ml-auto" />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Footer count */}
      <div className="px-4 py-2.5 border-t border-hairline text-[11px] text-muted flex items-center justify-between">
        <span className="tabular">
          Showing {filteredCases.length} of {cases.length} cases
        </span>
      </div>
    </div>
  )
}
