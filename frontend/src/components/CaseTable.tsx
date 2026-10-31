
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
  escalated:   'border-l-2 border-l-red-500/70',
  in_progress: 'border-l-2 border-l-amber-500/70',
  pending:     'border-l-2 border-l-zinc-700/70',
  recovered:   'border-l-2 border-l-emerald-500/70',
  closed:      'border-l-2 border-l-zinc-700/70',
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
    <div className="rounded-xl border border-zinc-800/80 overflow-hidden bg-[#0d0d12] shadow-2xl">
      <Table>
        <TableHeader className="bg-zinc-900/60 border-b border-zinc-800/80">
          <TableRow className="border-b border-zinc-800/80 hover:bg-transparent">
            <TableHead className="w-12 text-[11px] font-semibold text-zinc-500 uppercase tracking-widest pl-5">#</TableHead>
            <TableHead className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest min-w-[200px]">Customer</TableHead>
            <TableHead className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest">Status</TableHead>
            <TableHead className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest">Amount</TableHead>
            <TableHead className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest">Type</TableHead>
            <TableHead className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest">Channel</TableHead>
            <TableHead className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest">Next Scheduled</TableHead>
            <TableHead className="w-24 text-right pr-5"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <TableRow key={i} className="border-b border-zinc-800/40">
                <TableCell className="pl-5"><Skeleton className="h-4 w-6 bg-zinc-800/50" /></TableCell>
                <TableCell>
                  <Skeleton className="h-4 w-32 bg-zinc-800/50 mb-1.5" />
                  <Skeleton className="h-3 w-24 bg-zinc-800/30" />
                </TableCell>
                <TableCell><Skeleton className="h-5 w-20 rounded-full bg-zinc-800/50" /></TableCell>
                <TableCell><Skeleton className="h-4 w-16 bg-zinc-800/50" /></TableCell>
                <TableCell><Skeleton className="h-5 w-24 rounded-full bg-zinc-800/50" /></TableCell>
                <TableCell><Skeleton className="h-5 w-20 rounded-md bg-zinc-800/50" /></TableCell>
                <TableCell><Skeleton className="h-4 w-24 bg-zinc-800/50" /></TableCell>
                <TableCell className="pr-5 text-right"><Skeleton className="h-7 w-16 rounded-md bg-zinc-800/50 ml-auto" /></TableCell>
              </TableRow>
            ))
          ) : cases.length === 0 ? (
            <TableRow>
              <TableCell colSpan={8} className="py-20 text-center text-zinc-600 text-sm">
                No cases found. Run the agent to generate cases.
              </TableCell>
            </TableRow>
          ) : (
            cases.map((c, idx) => (
              <TableRow
                key={c.case_id}
                onClick={() => onRowClick(c.case_id)}
                className={`cursor-pointer hover:bg-zinc-800/40 border-b border-zinc-800/40 transition-colors group ${STATUS_ROW_BORDER[c.recovery_status] ?? 'border-l-2 border-l-transparent'}`}
              >
                {/* Index */}
                <TableCell className="pl-5 text-xs text-zinc-500 font-medium">
                  {idx + 1}
                </TableCell>

                {/* Customer */}
                <TableCell className="min-w-[200px]">
                  <p className="text-[13px] font-semibold text-zinc-200 truncate">{c.customer.name}</p>
                  <p className="text-[11px] text-zinc-500 truncate mt-0.5">{c.customer.email}</p>
                </TableCell>

                {/* Status */}
                <TableCell>
                  <StatusPill status={c.recovery_status} />
                </TableCell>

                {/* Amount */}
                <TableCell className={`text-[13px] font-semibold tracking-tight ${c.recovery_status === 'recovered' ? 'text-emerald-400' : 'text-zinc-300'}`}>
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
                <TableCell className="text-[12px] text-zinc-400 whitespace-nowrap">
                  {c.next_retry_at ? fmtTs(c.next_retry_at) : (c.recovery_status === 'closed' || c.recovery_status === 'recovered' ? '—' : 'Pending')}
                </TableCell>

                {/* Action */}
                <TableCell className="pr-5 text-right">
                  <button 
                    className="px-3 py-1.5 rounded-md bg-zinc-800/50 text-zinc-300 text-[11px] font-medium border border-zinc-700/50 opacity-0 group-hover:opacity-100 group-hover:bg-zinc-700 hover:text-white hover:border-zinc-500 transition-all"
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
