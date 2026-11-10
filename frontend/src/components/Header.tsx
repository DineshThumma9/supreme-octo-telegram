import { RotateCw, Trash2 } from 'lucide-react'

interface HeaderProps {
  title: string
  sseConnected?: boolean
  isRefreshing?: boolean
  onRefresh?: () => void
  onClearCases?: () => void
  onToggleSimulate?: () => void
  isSimulateOpen?: boolean
}

export function Header({
  title,
  sseConnected = true,
  isRefreshing = false,
  onRefresh,
  onClearCases,
  onToggleSimulate,
  isSimulateOpen = false,
}: HeaderProps) {
  return (
    <header className="sticky top-0 z-20 border-b border-hairline bg-page h-14 px-6 flex items-center justify-between shrink-0 select-none">
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-medium text-primary tracking-tight">{title}</h1>
        <div className="flex items-center gap-1.5 text-[11px] text-muted">
          <span className={`w-1.5 h-1.5 rounded-full ${sseConnected ? 'bg-[#4cc38a]' : 'bg-[#85858b]'}`} />
          <span>{sseConnected ? 'Live' : 'Offline'}</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {onClearCases && (
          <button
            onClick={onClearCases}
            className="h-7 px-2.5 rounded text-xs text-muted hover:text-[#e5484d] hover:bg-raised transition-colors flex items-center gap-1.5"
            title="Clear all cases"
          >
            <Trash2 className="w-3 h-3" />
            <span className="hidden sm:inline">Clear cases</span>
          </button>
        )}

        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            className="h-7 px-2.5 rounded border border-hairline bg-raised hover:bg-hover text-secondary hover:text-primary text-xs transition-colors flex items-center gap-1.5"
          >
            <RotateCw className={`w-3 h-3 ${isRefreshing ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
        )}

        {onToggleSimulate && (
          <button
            onClick={onToggleSimulate}
            className={`h-7 px-3 rounded text-xs font-medium transition-colors ${
              isSimulateOpen
                ? 'border border-hairline bg-raised text-primary hover:bg-hover'
                : 'bg-[#ededed] text-[#141415] hover:bg-white'
            }`}
          >
            {isSimulateOpen ? 'Close testbench' : 'Simulate failure'}
          </button>
        )}
      </div>
    </header>
  )
}
