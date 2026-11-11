import { useState, useMemo, useRef, useCallback, useEffect } from 'react'
import { AgGridReact } from 'ag-grid-react'
import {
  AllCommunityModule,
  ModuleRegistry,
  themeQuartz,
  type ColDef,
  type ICellRendererParams,
  type GridApi,
  type GridReadyEvent,
} from 'ag-grid-community'
import type { Case } from '../types'
import { fmt, fmtTs } from '../utils/formatters'
import { TypeBadge } from './TypeBadge'
import { StatusPill } from './StatusPill'
import { ChannelChip } from './ChannelChip'
import {
  Search,
  ChevronRight,
  Download,
  ChevronDown,
  Check,
  RotateCcw,
  SlidersHorizontal,
} from 'lucide-react'

// Register Community modules once at module load
ModuleRegistry.registerModules([AllCommunityModule])

// Dark theme matching Renvue Graphite design system
const gridTheme = themeQuartz.withParams({
  backgroundColor: '#19191b',
  foregroundColor: '#ededed',
  headerBackgroundColor: '#141415',
  headerTextColor: '#85858b',
  borderColor: 'rgba(237, 237, 237, 0.08)',
  rowHoverColor: '#232325',
  selectedRowBackgroundColor: '#232325',
  fontFamily: 'Geist, sans-serif',
  fontSize: '12px',
  headerFontSize: '11px',
  cellHorizontalPadding: '14px',
})

// Clean, natural business options (no academic jargon)
const CATEGORY_OPTIONS = [
  { value: 'all', label: 'All types' },
  { value: 'failed_payment', label: 'Failed payment' },
  { value: 'subscription_failed', label: 'Subscription halted' },
  { value: 'invoice_failed', label: 'Overdue invoice' },
  { value: 'abandoned_checkout', label: 'Abandoned checkout' },
]

const CHANNEL_OPTIONS = [
  { value: 'all', label: 'All channels' },
  { value: 'email_link', label: 'Email payment link' },
  { value: 'sms_link', label: 'SMS / WhatsApp' },
  { value: 'paypal_invoice_reminder', label: 'Invoice reminder' },
  { value: 'retry_now', label: 'Immediate retry' },
  { value: 'retry_payday', label: 'Payday retry' },
  { value: 'discount_link', label: 'Discount concession' },
  { value: 'update_method_link', label: 'Update payment method' },
  { value: 'human_escalation', label: 'Human escalation' },
]

const AMOUNT_TIER_OPTIONS = [
  { value: 'all', label: 'All amounts' },
  { value: 'micro', label: '< $100' },
  { value: 'mid', label: '$100 – $1,000' },
  { value: 'high', label: '$1,000 – $5,000' },
  { value: 'enterprise', label: '> $5,000' },
]

const TOUCH_OPTIONS = [
  { value: 'all', label: 'All attempts' },
  { value: '1', label: '1st touch' },
  { value: '2', label: '2nd touch' },
  { value: '3', label: '3rd touch (final)' },
]

interface FilterDropdownProps {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (val: string) => void
}

/**
 * Custom dark graphite dropdown menu.
 * Replaces ugly browser-native <select> (which turns bright blue on Linux/Chrome).
 */
function FilterDropdown({ label, value, options, onChange }: FilterDropdownProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const selectedOption = options.find((o) => o.value === value)
  const isActive = value !== 'all'

  return (
    <div ref={ref} className="relative inline-block text-left">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`h-7 px-2.5 rounded text-xs font-medium transition-colors border flex items-center gap-1.5 shrink-0 select-none ${
          isActive
            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
            : 'bg-raised/70 text-secondary hover:text-primary hover:bg-raised border-hairline'
        }`}
      >
        <span className="text-muted font-normal">{label}:</span>
        <span className="font-medium text-primary">{selectedOption?.label ?? label}</span>
        <ChevronDown className="w-3 h-3 text-muted ml-0.5" />
      </button>

      {open && (
        <div className="absolute left-0 mt-1.5 w-52 rounded-lg bg-[#18181b] border border-white/10 shadow-2xl py-1 z-50 text-xs text-primary focus:outline-none animate-in fade-in-50 duration-100">
          <div className="px-3 py-1 text-[10px] font-mono uppercase tracking-wider text-muted border-b border-white/5 mb-1">
            Filter by {label}
          </div>
          <div className="max-h-60 overflow-y-auto py-0.5">
            {options.map((opt) => {
              const selected = opt.value === value
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => {
                    onChange(opt.value)
                    setOpen(false)
                  }}
                  className={`w-full text-left px-3 py-1.5 flex items-center justify-between text-xs transition-colors ${
                    selected
                      ? 'bg-white/10 text-primary font-medium'
                      : 'text-secondary hover:text-primary hover:bg-white/5'
                  }`}
                >
                  <span className="truncate">{opt.label}</span>
                  {selected && <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0 ml-2" />}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

interface CaseGridProps {
  cases: Case[]
  loading: boolean
  onRowClick: (id: string) => void
  showFilterTabs?: boolean
  defaultStatusFilter?: string
  showControls?: boolean
}

export function CaseGrid({
  cases,
  loading,
  onRowClick,
  showFilterTabs = true,
  defaultStatusFilter = 'all',
  showControls = true,
}: CaseGridProps) {
  // Status tab filter
  const [statusFilter, setStatusFilter] = useState(defaultStatusFilter)

  // Quick customer search
  const [search, setSearch] = useState('')

  // Structured filters
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [channelFilter, setChannelFilter] = useState('all')
  const [amountTierFilter, setAmountTierFilter] = useState('all')
  const [touchFilter, setTouchFilter] = useState('all')

  const gridApiRef = useRef<GridApi<Case> | null>(null)

  const onGridReady = useCallback((params: GridReadyEvent<Case>) => {
    gridApiRef.current = params.api
  }, [])

  const activeFilterCount = useMemo(() => {
    let count = 0
    if (categoryFilter !== 'all') count++
    if (channelFilter !== 'all') count++
    if (amountTierFilter !== 'all') count++
    if (touchFilter !== 'all') count++
    if (search.trim()) count++
    return count
  }, [categoryFilter, channelFilter, amountTierFilter, touchFilter, search])

  const resetAllFilters = useCallback(() => {
    setCategoryFilter('all')
    setChannelFilter('all')
    setAmountTierFilter('all')
    setTouchFilter('all')
    setSearch('')
  }, [])

  // Filter application
  const filteredCases = useMemo(() => {
    return cases.filter((c) => {
      // 1. Status tab filter
      if (statusFilter === 'escalated' && c.recovery_status !== 'escalated') return false
      if (statusFilter === 'active' && ['escalated', 'recovered', 'closed'].includes(c.recovery_status)) return false
      if (statusFilter === 'recovered' && c.recovery_status !== 'recovered') return false
      if (statusFilter === 'closed' && c.recovery_status !== 'closed') return false

      // 2. Failure type filter
      if (categoryFilter !== 'all' && c.case_type !== categoryFilter) return false

      // 3. Channel filter
      if (channelFilter !== 'all') {
        const action = c.last_action_taken || ''
        if (!action.includes(channelFilter)) return false
      }

      // 4. Amount tier filter
      if (amountTierFilter !== 'all') {
        const amt = c.amount ?? 0
        if (amountTierFilter === 'micro' && amt >= 100) return false
        if (amountTierFilter === 'mid' && (amt < 100 || amt > 1000)) return false
        if (amountTierFilter === 'high' && (amt <= 1000 || amt > 5000)) return false
        if (amountTierFilter === 'enterprise' && amt <= 5000) return false
      }

      // 5. Attempt touch filter
      if (touchFilter !== 'all') {
        const touch = Number(touchFilter)
        if (c.attempt_count !== touch) return false
      }

      // 6. Customer identity search (name, email, case ID)
      if (search.trim()) {
        const q = search.toLowerCase()
        const name = (c.customer?.name || '').toLowerCase()
        const email = (c.customer?.email || '').toLowerCase()
        const caseId = (c.case_id || '').toLowerCase()
        if (!name.includes(q) && !email.includes(q) && !caseId.includes(q)) return false
      }

      return true
    })
  }, [cases, statusFilter, categoryFilter, channelFilter, amountTierFilter, touchFilter, search])

  const counts = useMemo(() => {
    return {
      all: cases.length,
      escalated: cases.filter((c) => c.recovery_status === 'escalated').length,
      active: cases.filter((c) => !['escalated', 'recovered', 'closed'].includes(c.recovery_status)).length,
      recovered: cases.filter((c) => c.recovery_status === 'recovered').length,
    }
  }, [cases])

  const handleExportCsv = useCallback(() => {
    if (gridApiRef.current) {
      gridApiRef.current.exportDataAsCsv({
        fileName: `renvue-cases-${statusFilter}-${new Date().toISOString().slice(0, 10)}.csv`,
      })
    }
  }, [statusFilter])

  const defaultColDef = useMemo<ColDef>(() => ({
    sortable: true,
    resizable: true,
    enableCellChangeFlash: true,
    suppressHeaderMenuButton: true, // Disables awkward in-grid popup that was misaligned with table
  }), [])

  // Explicitly defined columns with pure sorting on click
  const columnDefs = useMemo<ColDef<Case>[]>(() => [
    {
      headerName: '#',
      width: 50,
      valueGetter: (p) => (p.node?.rowIndex ?? 0) + 1,
      cellClass: 'text-muted tabular text-center',
      sortable: false,
      resizable: false,
      suppressMovable: true,
    },
    {
      headerName: 'Customer',
      minWidth: 210,
      flex: 1,
      valueGetter: (p) => p.data?.customer.name ?? 'Unknown',
      cellRenderer: (p: ICellRendererParams<Case>) => (
        <div className="min-w-0 py-1">
          <div className="font-medium text-primary truncate leading-tight">
            {p.data?.customer.name || 'Unknown'}
          </div>
          <div className="text-[11px] text-muted truncate mt-0.5 leading-tight">
            {p.data?.customer.email}
          </div>
        </div>
      ),
      sortable: true,
    },
    {
      headerName: 'Status',
      field: 'recovery_status',
      width: 130,
      cellRenderer: (p: ICellRendererParams<Case>) =>
        p.data ? <StatusPill status={p.data.recovery_status} /> : null,
      sortable: true,
    },
    {
      headerName: 'Amount',
      field: 'amount',
      width: 120,
      type: 'rightAligned',
      valueFormatter: (p) => `$${fmt(p.value ?? 0)}`,
      cellClass: 'tabular font-medium text-right',
      sortable: true,
    },
    {
      headerName: 'Touch',
      field: 'attempt_count',
      width: 95,
      cellRenderer: (p: ICellRendererParams<Case>) => {
        const count = p.data?.attempt_count ?? 1
        const dots = [1, 2, 3].map((i) => (
          <span
            key={i}
            className={`w-1.5 h-1.5 rounded-full ${
              i <= count
                ? count >= 3
                  ? 'bg-rose-400'
                  : count === 2
                  ? 'bg-amber-400'
                  : 'bg-emerald-400'
                : 'bg-muted/30'
            }`}
          />
        ))
        return (
          <div className="flex items-center gap-1.5 tabular text-xs">
            <div className="flex items-center gap-0.5">{dots}</div>
            <span className="text-muted text-[11px]">{count}/3</span>
          </div>
        )
      },
      sortable: true,
    },
    {
      headerName: 'Failure type',
      field: 'case_type',
      width: 165,
      cellRenderer: (p: ICellRendererParams<Case>) =>
        p.data ? <TypeBadge type={p.data.case_type} /> : null,
      sortable: true,
    },
    {
      headerName: 'Channel',
      field: 'last_action_taken',
      width: 145,
      cellRenderer: (p: ICellRendererParams<Case>) =>
        p.data ? <ChannelChip action={p.data.last_action_taken} /> : null,
      sortable: true,
    },
    {
      headerName: 'Next scheduled',
      field: 'next_retry_at',
      width: 155,
      valueFormatter: (p) => (p.value ? fmtTs(p.value) : '—'),
      cellClass: 'text-muted tabular',
      sortable: true,
    },
    {
      headerName: '',
      width: 44,
      sortable: false,
      resizable: false,
      cellRenderer: () => (
        <div className="flex items-center justify-center h-full">
          <ChevronRight className="w-3.5 h-3.5 text-muted" />
        </div>
      ),
    },
  ], [])

  return (
    <div className="rounded-lg border border-hairline bg-card overflow-hidden">
      {/* Controls Bar (shown on Cases page; omitted on compact Overview previews) */}
      {showControls && (
        <div className="border-b border-hairline divide-y divide-hairline">
          {/* Row 1: Status Tabs, Search & Export */}
          <div className="p-3 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
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
                  Needs approval{' '}
                  <span className={`tabular ml-1 ${counts.escalated > 0 ? 'text-[#e5484d]' : 'text-muted'}`}>
                    {counts.escalated}
                  </span>
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

            {/* Search & Export Actions */}
            <div className="flex items-center gap-2">
              <div className="relative w-full sm:w-56">
                <Search className="w-3.5 h-3.5 text-muted absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search customer, email…"
                  className="w-full h-7 pl-8 pr-3 rounded bg-deep border border-hairline text-xs text-primary placeholder:text-muted focus:border-focus focus:outline-none"
                />
              </div>

              <button
                onClick={handleExportCsv}
                disabled={filteredCases.length === 0}
                className="h-7 px-2.5 rounded bg-raised border border-hairline text-xs text-muted hover:text-primary transition-colors flex items-center gap-1.5 shrink-0 disabled:opacity-40"
                title="Export filtered rows to CSV"
              >
                <Download className="w-3 h-3" />
                <span className="hidden sm:inline">Export CSV</span>
              </button>
            </div>
          </div>

          {/* Row 2: Clean, dark-themed filter pills */}
          <div className="px-3 py-2 bg-raised/30 flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-muted flex items-center gap-1 mr-1">
              <SlidersHorizontal className="w-3 h-3" />
              <span>Filters:</span>
            </span>

            <FilterDropdown
              label="Type"
              value={categoryFilter}
              options={CATEGORY_OPTIONS}
              onChange={setCategoryFilter}
            />

            <FilterDropdown
              label="Channel"
              value={channelFilter}
              options={CHANNEL_OPTIONS}
              onChange={setChannelFilter}
            />

            <FilterDropdown
              label="Amount"
              value={amountTierFilter}
              options={AMOUNT_TIER_OPTIONS}
              onChange={setAmountTierFilter}
            />

            <FilterDropdown
              label="Touch"
              value={touchFilter}
              options={TOUCH_OPTIONS}
              onChange={setTouchFilter}
            />

            {activeFilterCount > 0 && (
              <button
                onClick={resetAllFilters}
                className="h-7 px-2 text-[11px] text-muted hover:text-primary transition-colors flex items-center gap-1 ml-auto"
                title="Reset all active filters"
              >
                <RotateCcw className="w-3 h-3" />
                <span>Reset</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* AG Grid Component */}
      <div className="w-full overflow-hidden">
        <AgGridReact<Case>
          theme={gridTheme}
          rowData={loading ? [] : filteredCases}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          getRowId={(p) => p.data.case_id}
          domLayout="autoHeight"
          rowHeight={52}
          headerHeight={38}
          loading={loading}
          suppressCellFocus
          onGridReady={onGridReady}
          onRowClicked={(e) => e.data && onRowClick(e.data.case_id)}
          rowStyle={{ cursor: 'pointer' }}
          overlayNoRowsTemplate={
            search || activeFilterCount > 0
              ? 'No recovery cases match the selected filters.'
              : 'No recovery cases in this view.'
          }
        />
      </div>

      {/* Grid Footer with AG Grid attribution & stats */}
      <div className="p-3 border-t border-hairline bg-raised/30 flex items-center justify-between text-[11px] text-muted">
        <div>
          Showing <span className="tabular font-medium text-secondary">{filteredCases.length}</span> of{' '}
          <span className="tabular font-medium text-secondary">{cases.length}</span> recovery cases
          {activeFilterCount > 0 && (
            <span className="text-emerald-400 ml-1.5 font-mono">({activeFilterCount} active filters)</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-raised border border-hairline text-muted">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
            <span>AG Grid Community v36</span>
          </span>
          <span className="hidden sm:inline text-muted/60">· Virtualized DOM rendering</span>
        </div>
      </div>
    </div>
  )
}
