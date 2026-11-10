import {
  ChevronLeft,
  ChevronRight,
  FlaskConical,
  Layers,
  LayoutDashboard,
  type LucideIcon,
} from 'lucide-react'

export type NavView = 'overview' | 'cases' | 'agent-lab'

interface NavItem {
  id: NavView
  label: string
  icon: LucideIcon
  count?: number
  tag?: string
}

interface SidebarProps {
  activeView: NavView
  onViewChange: (view: NavView) => void
  escalatedCount?: number
  totalCasesCount?: number
  collapsed: boolean
  onToggle: () => void
}

export function Sidebar({
  activeView,
  onViewChange,
  escalatedCount = 0,
  totalCasesCount = 0,
  collapsed,
  onToggle,
}: SidebarProps) {
  const navItems: NavItem[] = [
    {
      id: 'overview',
      label: 'Overview',
      icon: LayoutDashboard,
    },
    {
      id: 'cases',
      label: 'Cases',
      icon: Layers,
      count: escalatedCount > 0 ? escalatedCount : (totalCasesCount > 0 ? totalCasesCount : undefined),
    },
    {
      id: 'agent-lab',
      label: 'Agent lab',
      icon: FlaskConical,
      tag: 'ML',
    },
  ]

  return (
    <aside
      className={`fixed left-0 top-0 bottom-0 border-r border-hairline bg-deep z-30 flex flex-col transition-[width] duration-150 select-none ${
        collapsed ? 'w-[60px]' : 'w-56'
      }`}
    >
      {/* Brand Header */}
      <div
        className={`flex items-center border-b border-hairline shrink-0 h-14 ${
          collapsed ? 'justify-center px-2' : 'justify-between px-4'
        }`}
      >
        <div className="flex items-center gap-2.5">
          <svg
            className="w-4 h-4 text-primary shrink-0"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
          </svg>
          {!collapsed && (
            <span className="font-medium text-sm text-primary tracking-tight">Renvue</span>
          )}
        </div>

        <button
          onClick={onToggle}
          className={`p-1 rounded text-muted hover:text-primary hover:bg-raised transition-colors ${
            collapsed ? 'hidden' : 'block'
          }`}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <ChevronLeft className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Main Navigation */}
      <nav className="flex-1 px-2 py-3 space-y-1" aria-label="Main navigation">
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive = activeView === item.id

          return (
            <button
              key={item.id}
              onClick={() => onViewChange(item.id)}
              title={collapsed ? item.label : undefined}
              className={`w-full flex items-center h-8 rounded text-xs font-medium transition-colors ${
                collapsed
                  ? 'justify-center px-2'
                  : 'justify-between px-2.5'
              } ${
                isActive
                  ? 'bg-raised text-primary'
                  : 'text-secondary hover:text-primary hover:bg-raised/50'
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <Icon
                  className={`w-4 h-4 shrink-0 ${
                    isActive ? 'text-primary' : 'text-muted'
                  }`}
                  strokeWidth={1.5}
                />
                {!collapsed && (
                  <span className="truncate">{item.label}</span>
                )}
              </div>

              {!collapsed && (
                item.count !== undefined ? (
                  <span className={`text-[11px] tabular ${item.id === 'cases' && escalatedCount > 0 ? 'text-[#e5484d]' : 'text-muted'}`}>
                    {item.count}
                  </span>
                ) : item.tag ? (
                  <span className="text-[10px] text-muted font-mono uppercase tracking-wider">
                    {item.tag}
                  </span>
                ) : null
              )}
            </button>
          )
        })}
      </nav>

      {/* Expand Button if Collapsed */}
      {collapsed && (
        <div className="p-2 flex justify-center border-t border-hairline">
          <button
            onClick={onToggle}
            className="p-1 rounded text-muted hover:text-primary hover:bg-raised transition-colors"
            title="Expand sidebar"
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Footer: Merchant Sandbox Status */}
      <div className={`shrink-0 border-t border-hairline ${collapsed ? 'p-2' : 'px-3 py-3'}`}>
        <div className={`flex items-center gap-2.5 ${collapsed ? 'justify-center' : ''}`}>
          <div className="w-2 h-2 rounded-full bg-[#4cc38a] shrink-0" />
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <div className="text-[11px] font-medium text-primary truncate">PayPal sandbox</div>
              <div className="text-[10px] text-muted truncate">Connected</div>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}
