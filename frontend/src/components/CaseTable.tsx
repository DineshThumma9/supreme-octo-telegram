
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import type { Case } from "../types"
import { fmt, fmtTs } from "../utils/formatters"
import { TypeBadge } from "./TypeBadge"
import { StatusPill } from "./StatusPill"
import { ChannelChip } from "./ChannelChip"

const STATUS_ROW_BORDER: Record<string, string> = {
  escalated:   'border-l-2 border-l-red-500/80',
  in_progress: 'border-l-2 border-l-amber-500/80',
  pending:     'border-l-2 border-l-zinc-700',
  recovered:   'border-l-2 border-l-emerald-500/80',
  closed:      'border-l-2 border-l-zinc-800',
}

export function CaseTable({
  cases,
  loading,
  onRowClick,
}: {
  cases: Case[]
  loading: boolean
  onRowClick: (id: string) => void
}) {
  return (
    <div className="rounded-lg border border-zinc-800 overflow-hidden bg-[#18181b]">
      <Table>
        <TableHeader className="bg-zinc-900/80 border-b border-zinc-800">
          <TableRow className="border-b border-zinc-800 hover:bg-transparent">
            <TableHead className="w-12 text-xs font-normal text-zinc-400 pl-4">#</TableHead>
            <TableHead className="text-xs font-normal text-zinc-400 min-w-[200px]">Customer</TableHead>
            <TableHead className="text-xs font-normal text-zinc-400">Status</TableHead>
            <TableHead className="text-xs font-normal text-zinc-400">Amount</TableHead>
            <TableHead className="text-xs font-normal text-zinc-400">Type</TableHead>
            <TableHead className="text-xs font-normal text-zinc-400">Channel</TableHead>
            <TableHead className="text-xs font-normal text-zinc-400">Next scheduled</TableHead>
            <TableHead className="w-20 text-right pr-4"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <TableRow key={i} className="border-b border-zinc-800/40">
                <TableCell className="pl-4"><Skeleton className="h-4 w-5 bg-zinc-800" /></TableCell>
                <TableCell>
                  <Skeleton className="h-4 w-28 bg-zinc-800 mb-1" />
                  <Skeleton className="h-3 w-20 bg-zinc-800/50" />
                </TableCell>
                <TableCell><Skeleton className="h-4 w-16 rounded bg-zinc-800" /></TableCell>
                <TableCell><Skeleton className="h-4 w-14 bg-zinc-800" /></TableCell>
                <TableCell><Skeleton className="h-4 w-20 rounded bg-zinc-800" /></TableCell>
                <TableCell><Skeleton className="h-4 w-16 bg-zinc-800" /></TableCell>
                <TableCell><Skeleton className="h-4 w-20 bg-zinc-800" /></TableCell>
                <TableCell className="pr-4 text-right"><Skeleton className="h-6 w-14 rounded bg-zinc-800 ml-auto" /></TableCell>
              </TableRow>
            ))
          ) : cases.length === 0 ? (
            <TableRow>
              <TableCell colSpan={8} className="py-16 text-center text-zinc-500 text-xs">
                No cases found
              </TableCell>
            </TableRow>
          ) : (
            cases.map((c, idx) => (
              <TableRow
                key={c.case_id}
                onClick={() => onRowClick(c.case_id)}
                className={`cursor-pointer hover:bg-zinc-800/50 border-b border-zinc-800/50 transition-colors group ${STATUS_ROW_BORDER[c.recovery_status] ?? 'border-l-2 border-l-transparent'}`}
              >
                {/* Index */}
                <TableCell className="pl-4 text-xs text-zinc-500 tabular font-mono">
                  {idx + 1}
                </TableCell>

                {/* Customer */}
                <TableCell className="min-w-[200px]">
                  <p className="text-xs font-medium text-zinc-200 truncate">{c.customer.name}</p>
                  <p className="text-[11px] text-zinc-500 truncate mt-0.5">{c.customer.email}</p>
                </TableCell>

                {/* Status */}
                <TableCell>
                  <StatusPill status={c.recovery_status} />
                </TableCell>

                {/* Amount */}
                <TableCell className={`text-xs tabular font-medium ${c.recovery_status === 'recovered' ? 'text-emerald-400' : 'text-zinc-200'}`}>
                  ${fmt(c.amount)}
                </TableCell>

                {/* Type */}
                <TableCell>
                  <TypeBadge type={c.case_type} />
                </TableCell>

                {/* Channel */}
                <TableCell>
                  <ChannelChip action={c.last_action_taken} />
                </TableCell>

                {/* Next Scheduled */}
                <TableCell className="text-xs text-zinc-400 tabular whitespace-nowrap">
                  {c.next_retry_at ? fmtTs(c.next_retry_at) : (c.recovery_status === 'closed' || c.recovery_status === 'recovered' ? '—' : 'Pending')}
                </TableCell>

                {/* Action */}
                <TableCell className="pr-4 text-right">
                  <button 
                    className="px-2 py-1 rounded bg-zinc-800/60 text-zinc-300 text-[11px] border border-zinc-700/60 opacity-0 group-hover:opacity-100 hover:bg-zinc-700 hover:text-white transition-opacity"
                    onClick={(e) => { e.stopPropagation(); onRowClick(c.case_id); }}
                  >
                    Inspect
                  </button>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}
