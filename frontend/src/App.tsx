import { useEffect, useState, lazy, Suspense } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'

import { Sidebar, type NavView } from './components/Sidebar'
import { Header } from './components/Header'
import { StatsBar } from './components/StatsBar'
import { EscalationPanel } from './components/EscalationPanel'
import { CaseDrawer } from './components/CaseDrawer'
import { AgentLab } from './components/AgentLab'

const CaseGrid = lazy(() => import('./components/CaseGrid').then((m) => ({ default: m.CaseGrid })))
const VizStudio = lazy(() => import('./components/VizStudio').then((m) => ({ default: m.VizStudio })))

import { Sheet, SheetContent } from '@/components/ui/sheet'
import { fetchCase, simulateFire, simulateAction, clearAllCases } from './api'
import { useCaseStore } from './store/useCaseStore'
import type { Case } from './types'
import {
  Send,
  Loader2,
  FastForward,
  CreditCard,
  RotateCcw,
  X,
  MessageSquare,
  ArrowRight,
  ExternalLink,
  Copy,
  Check,
} from 'lucide-react'

function renderMessageWithLinks(text: string, fallbackUrl?: string | null) {
  const urlMatch = text.match(/https?:\/\/[^\s]+/)
  const targetUrl = urlMatch ? urlMatch[0] : fallbackUrl

  if (!targetUrl) {
    const urlRegex = /(https?:\/\/[^\s]+)/g
    const parts = text.split(urlRegex)
    return parts.map((part, i) => {
      if (part.match(urlRegex)) {
        return (
          <a
            key={i}
            href={part}
            target="_blank"
            rel="noopener noreferrer"
            className="text-emerald-400 hover:text-emerald-300 underline font-mono break-all inline-flex items-center gap-0.5 select-text font-medium cursor-pointer"
            onClick={(e) => e.stopPropagation()}
          >
            <span>{part}</span>
            <ExternalLink className="w-2.5 h-2.5 inline shrink-0 ml-0.5" />
          </a>
        )
      }
      return <span key={i} className="select-text">{part}</span>
    })
  }

  const pattern = /(https?:\/\/[^\s]+|\b(?:this\s+link|the\s+link|payment\s+link|invoice\s+link|checkout\s+link|link)\b)/gi
  const parts = text.split(pattern)
  return parts.map((part, i) => {
    if (!part) return null
    if (part.match(/https?:\/\/[^\s]+/i)) {
      return (
        <a
          key={i}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="text-emerald-400 hover:text-emerald-300 underline font-mono text-[11px] break-all inline-flex items-center gap-0.5 select-text font-medium cursor-pointer"
          onClick={(e) => e.stopPropagation()}
        >
          <span>{part}</span>
          <ExternalLink className="w-2.5 h-2.5 inline shrink-0 ml-0.5" />
        </a>
      )
    }
    if (part.match(/^(?:this\s+link|the\s+link|payment\s+link|invoice\s+link|checkout\s+link|link)$/i)) {
      return (
        <a
          key={i}
          href={targetUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-emerald-400 hover:text-emerald-300 underline font-medium inline-flex items-center gap-0.5 select-text cursor-pointer"
          onClick={(e) => e.stopPropagation()}
        >
          <span>{part}</span>
          <ExternalLink className="w-2.5 h-2.5 inline shrink-0 ml-0.5" />
        </a>
      )
    }
    return <span key={i} className="select-text">{part}</span>
  })
}

export default function App() {
  const [drawerWidth, setDrawerWidth] = useState(600)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  // URL hash sync for proper view navigation (no more redundant anchor scrolling!)
  const [activeView, setActiveView] = useState<NavView>(() => {
    const hash = window.location.hash.replace('#', '')
    if (hash === 'agent-lab' || hash === 'cases' || hash === 'analytics' || hash === 'charts') {
      return (hash === 'charts' ? 'analytics' : hash) as NavView
    }
    if (hash === 'grid') return 'cases'
    return 'overview'
  })

  useEffect(() => {
    const handleHash = () => {
      const hash = window.location.hash.replace('#', '')
      if (hash === 'agent-lab' || hash === 'cases' || hash === 'analytics' || hash === 'charts') {
        setActiveView((hash === 'charts' ? 'analytics' : hash) as NavView)
      } else if (hash === 'grid') {
        setActiveView('cases')
      } else {
        setActiveView('overview')
      }
    }
    window.addEventListener('hashchange', handleHash)
    return () => window.removeEventListener('hashchange', handleHash)
  }, [])

  const handleViewChange = (view: NavView) => {
    setActiveView(view)
    window.location.hash = view
  }

  const {
    cases,
    stats,
    loadingCases,
    loadingStats,
    selectedCaseId,
    drawerOpen,
    sseConnected,
    setSelectedCaseId,
    setDrawerOpen,
    refreshData,
    initSSE,
  } = useCaseStore()

  useEffect(() => {
    refreshData()
    const cleanupSSE = initSSE()
    const id = setInterval(refreshData, 20000)
    return () => {
      cleanupSSE()
      clearInterval(id)
    }
  }, [refreshData, initSSE])

  const openDrawer = (id: string) => {
    setSelectedCaseId(id)
    setDrawerOpen(true)
  }

  const escalatedCases = cases.filter((c) => c.recovery_status === 'escalated')
  const recoveredCases = cases.filter((c) => c.recovery_status === 'recovered' || c.recovery_status === 'closed')
  const processingCases = cases.filter((c) => !['escalated', 'recovered', 'closed'].includes(c.recovery_status))

  // Simulation testbench state
  const [simulate, setSimulate] = useState(false)
  const [step, setStep] = useState<1 | 2>(1)
  const [isSimulating, setIsSimulating] = useState(false)
  const [isPolling, setIsPolling] = useState(false)

  const [eventType, setEventType] = useState('order.failed')
  const [declineReason, setDeclineReason] = useState('Insufficient funds')

  const handleScenarioChange = (val: string) => {
    setEventType(val)
    if (val === 'order.failed') setDeclineReason('Insufficient funds')
    else if (val === 'subscription_failed') setDeclineReason('Recurring billing failure')
    else if (val === 'invoice_failed') setDeclineReason('Invoice overdue')
    else if (val === 'abandoned_checkout') setDeclineReason('Checkout abandoned')
  }

  const [amount, setAmount] = useState('480')
  const [name, setName] = useState('Alex Morgan')
  const [email, setEmail] = useState('alex.morgan@example.com')

  const [activeCaseId, setActiveCaseId] = useState<string | null>(null)
  const [activeCase, setActiveCase] = useState<Case | null>(null)
  const [replyText, setReplyText] = useState('')

  const storeCase = useCaseStore((state) => state.cases.find((c) => c.case_id === activeCaseId))

  useEffect(() => {
    if (storeCase && activeCaseId) {
      setActiveCase(storeCase)
      if (['recovered', 'closed', 'escalated'].includes(storeCase.recovery_status)) {
        setIsPolling(false)
      }
    }
  }, [storeCase, activeCaseId])

  const resetState = () => {
    setStep(1)
    setIsSimulating(false)
    setIsPolling(false)
    setActiveCaseId(null)
    setActiveCase(null)
    setReplyText('')
  }

  const handleFireEvent = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    setIsSimulating(true)

    const payload = {
      event_type: eventType,
      decline_reason: declineReason,
      amount: Number(amount) || 480,
      name: name || 'Alex Morgan',
      email: email || 'alex.morgan@example.com',
    }

    try {
      const data = await simulateFire(payload)
      if (data.id) {
        setActiveCaseId(data.id)
        setStep(2)
        setIsPolling(true)
      }
    } catch (error) {
      console.error('Simulation trigger failed', error)
    } finally {
      setIsSimulating(false)
    }
  }

  const pollCaseStatus = async () => {
    if (!activeCaseId) return
    try {
      const caseData = await fetchCase(activeCaseId)
      if (!caseData) return
      setActiveCase(caseData)

      if (['recovered', 'closed', 'escalated'].includes(caseData.recovery_status)) {
        setIsPolling(false)
      }
    } catch (error) {
      console.error('Poll failed', error)
    }
  }

  const handleAction = async (actionType: 'pay' | 'ignore' | 'reply', msgContent?: string) => {
    if (!activeCaseId) return
    setIsSimulating(true)

    if (actionType === 'reply' && msgContent) {
      setReplyText('')
    }

    try {
      await simulateAction({
        case_id: activeCaseId,
        actions: actionType,
        messages: msgContent || '',
      })
      await pollCaseStatus()
      refreshData()
    } catch (error) {
      console.error('Action dispatch failed', error)
    } finally {
      setIsSimulating(false)
    }
  }

  useEffect(() => {
    if (!isPolling || !activeCaseId) return
    const interval = setInterval(pollCaseStatus, 2500)
    return () => clearInterval(interval)
  }, [isPolling, activeCaseId])

  const latestNextContact = (() => {
    if (activeCase?.next_retry_at) return activeCase.next_retry_at
    if (activeCase?.audit_log && activeCase.audit_log.length > 0) {
      const reversed = [...activeCase.audit_log].reverse()
      const entry = reversed.find((l) => l.next_contact)
      if (entry?.next_contact) return entry.next_contact
    }
    return null
  })()

  const latestAgentMessage = (() => {
    if (activeCase?.audit_log && activeCase.audit_log.length > 0) {
      const reversed = [...activeCase.audit_log].reverse()
      const lastOutbound = reversed.find(
        (l) =>
          l.direction === 'outbound' ||
          l.channel === 'whatsapp' ||
          l.event_triggered.startsWith('send_') ||
          l.event_triggered.startsWith('create_'),
      )
      if (lastOutbound?.message) {
        const nextStr = lastOutbound.next_contact ? ` · Next: ${new Date(lastOutbound.next_contact).toLocaleDateString()}` : ''
        return lastOutbound.message + nextStr
      }
    }
    const payLink = activeCase?.case_metadata?.payment_link
    const linkStr = payLink ? ` Tap link to retry: ${payLink}` : ''
    return `Hi ${name}, your payment of $${Number(amount || 0).toLocaleString()} didn't go through. Your order is reserved.${linkStr}`
  })()

  const [copiedLink, setCopiedLink] = useState(false)
  const handleCopyLink = (url: string) => {
    navigator.clipboard.writeText(url)
    setCopiedLink(true)
    setTimeout(() => setCopiedLink(false), 2000)
  }

  const extractedUrl = (() => {
    const match = latestAgentMessage.match(/https?:\/\/[^\s]+/)
    if (match) return match[0]
    return activeCase?.case_metadata?.payment_link || null
  })()

  const headerTitle =
    activeView === 'overview'
      ? 'Overview'
      : activeView === 'cases'
      ? 'Cases'
      : activeView === 'agent-lab'
      ? 'Agent lab'
      : 'Analytics'

  return (
    <TooltipProvider delay={0}>
      <div className="flex h-screen overflow-hidden text-primary bg-page">
        {/* Sidebar with actual page navigation */}
        <Sidebar
          activeView={activeView}
          onViewChange={handleViewChange}
          escalatedCount={escalatedCases.length}
          totalCasesCount={cases.length}
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
        />

        <div
          className={`flex-1 flex flex-col min-w-0 transition-[padding-left] duration-150 ${
            sidebarCollapsed ? 'pl-[60px]' : 'pl-56'
          }`}
        >
          {/* Top Header */}
          <Header
            title={headerTitle}
            sseConnected={sseConnected}
            isRefreshing={loadingCases || loadingStats}
            onRefresh={refreshData}
            onClearCases={async () => {
              if (confirm('Clear all cases from database?')) {
                await clearAllCases()
                refreshData()
              }
            }}
            onToggleSimulate={() => setSimulate(!simulate)}
            isSimulateOpen={simulate}
          />

          {/* Main Content Area */}
          <main className="flex-1 overflow-y-auto px-6 py-6">
            <div className="max-w-6xl mx-auto space-y-6">
              {/* Simulation Testbench */}
                {simulate && (
                  <div className="rounded-lg border border-hairline bg-card p-4">
                  {step === 1 ? (
                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-medium text-primary">Simulation testbench</span>
                        <button
                          onClick={() => setSimulate(false)}
                          className="p-1 rounded text-muted hover:text-primary transition-colors"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>

                      {/* Scenarios */}
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                        {[
                          { id: 'order.failed', label: 'Soft decline', sub: 'Insufficient funds' },
                          { id: 'subscription_failed', label: 'Subscription failure', sub: 'Recurring billing' },
                          { id: 'invoice_failed', label: 'Overdue invoice', sub: 'Invoice reminder' },
                          { id: 'abandoned_checkout', label: 'Abandoned checkout', sub: 'Cart session' },
                        ].map((sc) => {
                          const isSelected = eventType === sc.id
                          return (
                            <button
                              key={sc.id}
                              type="button"
                              onClick={() => handleScenarioChange(sc.id)}
                              className={`p-2.5 rounded border text-left transition-colors ${
                                isSelected
                                  ? 'border-focus bg-raised'
                                  : 'border-hairline bg-page hover:bg-raised/60'
                              }`}
                            >
                              <div className="text-xs font-medium text-primary">{sc.label}</div>
                              <div className="text-[11px] text-muted mt-0.5">{sc.sub}</div>
                            </button>
                          )
                        })}
                      </div>

                      {/* Customer inputs */}
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-3 border-t border-hairline">
                        <div>
                          <label className="block text-muted text-[11px] mb-1">Customer name</label>
                          <input
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="Alex Morgan"
                            className="w-full h-8 px-2.5 rounded bg-raised border border-hairline text-xs text-primary focus:border-focus focus:outline-none"
                          />
                        </div>
                        <div>
                          <label className="block text-muted text-[11px] mb-1">Amount (USD)</label>
                          <input
                            type="number"
                            value={amount}
                            onChange={(e) => setAmount(e.target.value)}
                            placeholder="480"
                            min="1"
                            step="any"
                            className="w-full h-8 px-2.5 rounded bg-raised border border-hairline text-xs text-primary tabular focus:border-focus focus:outline-none"
                          />
                        </div>
                        <div>
                          <label className="block text-muted text-[11px] mb-1">Email address</label>
                          <input
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            placeholder="alex@example.com"
                            className="w-full h-8 px-2.5 rounded bg-raised border border-hairline text-xs text-primary focus:border-focus focus:outline-none"
                          />
                        </div>
                      </div>

                      <div className="flex justify-end pt-1">
                        <button
                          type="button"
                          onClick={() => handleFireEvent()}
                          disabled={isSimulating}
                          className="h-8 px-4 rounded bg-[#ededed] text-[#141415] hover:bg-white text-xs font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5"
                        >
                          {isSimulating ? (
                            <>
                              <Loader2 className="w-3 h-3 animate-spin" />
                              <span>Simulating…</span>
                            </>
                          ) : (
                            <span>Run scenario</span>
                          )}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1 p-3 rounded bg-raised border border-hairline text-xs select-text">
                          <div className="text-[11px] text-muted mb-2 flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center gap-1.5">
                              <MessageSquare className="w-3.5 h-3.5 text-muted" />
                              <span>WhatsApp to {name} · <strong className="tabular font-medium text-secondary">${amount || '0'}</strong></span>
                            </div>

                            {extractedUrl && (
                              <div className="flex items-center gap-1.5">
                                <button
                                  type="button"
                                  onClick={() => handleCopyLink(extractedUrl)}
                                  className="px-2 py-0.5 rounded bg-card hover:bg-hover border border-hairline text-[10px] text-secondary hover:text-primary transition-colors flex items-center gap-1 cursor-pointer"
                                  title="Copy payment link"
                                >
                                  {copiedLink ? <Check className="w-2.5 h-2.5 text-emerald-400" /> : <Copy className="w-2.5 h-2.5" />}
                                  <span>{copiedLink ? 'Copied' : 'Copy link'}</span>
                                </button>
                                <a
                                  href={extractedUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="px-2.5 py-0.5 rounded bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-[10px] font-medium transition-colors flex items-center gap-1 cursor-pointer"
                                >
                                  <span>Open link</span>
                                  <ExternalLink className="w-2.5 h-2.5" />
                                </a>
                              </div>
                            )}
                          </div>
                          <p className="text-secondary leading-relaxed whitespace-pre-wrap select-text selection:bg-emerald-500/20">
                            {renderMessageWithLinks(latestAgentMessage, extractedUrl)}
                          </p>
                        </div>

                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            onClick={resetState}
                            className="h-7 px-2 rounded text-xs text-muted hover:text-primary hover:bg-raised transition-colors flex items-center gap-1"
                          >
                            <RotateCcw className="w-3 h-3" />
                            <span>New</span>
                          </button>
                          <button
                            onClick={() => setSimulate(false)}
                            className="p-1 rounded text-muted hover:text-primary hover:bg-raised transition-colors"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
                        <div className="flex items-center gap-2">
                          <span>{activeCase?.case_metadata?.ptp_date ? 'Promise to pay:' : 'Next retry:'}</span>
                          <span className="text-secondary tabular">
                            {activeCase?.case_metadata?.ptp_date
                              ? `${new Date(activeCase.case_metadata.ptp_date).toLocaleDateString()} (Reminders paused)`
                              : activeCase?.next_retry_at
                              ? new Date(activeCase.next_retry_at).toLocaleDateString()
                              : latestNextContact
                              ? new Date(latestNextContact).toLocaleDateString()
                              : 'None scheduled'}
                          </span>
                          <span>·</span>
                          <span>Attempt <strong className="text-secondary font-normal tabular">{activeCase?.attempt_count ?? 1}/3</strong></span>
                        </div>

                        {activeCaseId && (
                          <span className="font-mono text-[11px] text-muted">Case ID: {activeCaseId}</span>
                        )}
                      </div>

                      {activeCase && ['recovered', 'closed', 'escalated'].includes(activeCase.recovery_status) ? (
                        <div className="p-3 rounded bg-raised border border-hairline flex items-center justify-between text-xs">
                          <span className="text-secondary">
                            {activeCase.recovery_status === 'escalated'
                              ? 'Case escalated to human support'
                              : `Payment marked as ${activeCase.recovery_status}`}
                          </span>
                          <button
                            onClick={resetState}
                            className="h-7 px-2.5 rounded bg-[#ededed] text-[#141415] hover:bg-white text-xs font-medium"
                          >
                            New simulation
                          </button>
                        </div>
                      ) : (
                        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 pt-1">
                          <button
                            onClick={() => handleAction('ignore')}
                            disabled={isSimulating}
                            className="h-8 px-3 rounded border border-hairline bg-raised hover:bg-hover text-secondary hover:text-primary text-xs flex items-center gap-1.5 transition-colors disabled:opacity-50"
                          >
                            <FastForward className="w-3 h-3 text-muted" />
                            <span>Trigger next follow-up</span>
                          </button>

                          <button
                            onClick={() => handleAction('pay')}
                            disabled={isSimulating}
                            className="h-8 px-3 rounded border border-hairline bg-raised hover:bg-hover text-secondary hover:text-primary text-xs flex items-center gap-1.5 transition-colors disabled:opacity-50"
                          >
                            <CreditCard className="w-3 h-3 text-muted" />
                            <span>Settle payment</span>
                          </button>

                          <form
                            className="flex-1 flex items-center gap-1 bg-raised border border-hairline rounded px-2 h-8"
                            onSubmit={(e) => {
                              e.preventDefault()
                              if (replyText.trim()) handleAction('reply', replyText)
                            }}
                          >
                            <input
                              value={replyText}
                              onChange={(e) => setReplyText(e.target.value)}
                              placeholder="Simulate customer reply…"
                              className="w-full bg-transparent border-0 text-xs text-primary placeholder:text-muted focus:outline-none"
                              disabled={isSimulating}
                            />
                            <button
                              type="submit"
                              disabled={!replyText.trim() || isSimulating}
                              className="p-1 rounded text-muted hover:text-primary disabled:opacity-30"
                            >
                              <Send className="w-3 h-3" />
                            </button>
                          </form>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* VIEW 1: OVERVIEW */}
              {activeView === 'overview' && (
                <div className="space-y-6">
                  <StatsBar
                    stats={stats}
                    loading={loadingStats}
                    onReviewEscalated={() => handleViewChange('cases')}
                  />

                  {/* Escalation panel */}
                  <EscalationPanel
                    cases={escalatedCases}
                    onSelect={openDrawer}
                    onApprove={refreshData}
                  />

                  {/* Active Processing Queue Preview */}
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <div>
                        <h2 className="text-xs font-medium text-primary">Active processing queue</h2>
                        <p className="text-xs text-muted mt-0.5">
                          {loadingCases ? 'Loading cases…' : `${processingCases.length} active recovery flows`}
                        </p>
                      </div>
                      <button
                        onClick={() => handleViewChange('cases')}
                        className="text-xs text-secondary hover:text-primary flex items-center gap-1 transition-colors"
                      >
                        <span>View all cases</span>
                        <ArrowRight className="w-3 h-3" />
                      </button>
                    </div>

                    <Suspense
                      fallback={
                        <div className="h-48 flex items-center justify-center rounded-lg border border-hairline bg-card text-xs text-muted">
                          <Loader2 className="w-4 h-4 animate-spin mr-2" />
                          <span>Loading queue…</span>
                        </div>
                      }
                    >
                      <CaseGrid
                        cases={processingCases.slice(0, 10)}
                        loading={loadingCases}
                        onRowClick={openDrawer}
                        showFilterTabs={false}
                        showControls={false}
                      />
                    </Suspense>
                  </div>

                  {/* Successfully Recovered preview */}
                  {recoveredCases.length > 0 && (
                    <div>
                      <div className="flex items-center justify-between mb-3">
                        <div>
                          <h2 className="text-xs font-medium text-primary">Resolved & recovered</h2>
                          <p className="text-xs text-muted mt-0.5">
                            {recoveredCases.length} successfully recovered cases
                          </p>
                        </div>
                      </div>

                      <Suspense
                        fallback={
                          <div className="h-48 flex items-center justify-center rounded-lg border border-hairline bg-card text-xs text-muted">
                            <Loader2 className="w-4 h-4 animate-spin mr-2" />
                            <span>Loading resolved cases…</span>
                          </div>
                        }
                      >
                        <CaseGrid
                          cases={recoveredCases.slice(0, 5)}
                          loading={loadingCases}
                          onRowClick={openDrawer}
                          showFilterTabs={false}
                          showControls={false}
                        />
                      </Suspense>
                    </div>
                  )}
                </div>
              )}

              {/* VIEW 2: CASES (POWERED BY AG GRID) */}
              {activeView === 'cases' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <h2 className="text-xs font-medium text-primary">All recovery cases</h2>
                        <span className="px-1.5 py-0.5 text-[10px] font-mono rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                          AG Grid
                        </span>
                      </div>
                      <p className="text-xs text-muted mt-0.5">
                        {cases.length} total operational cases recorded · High-performance virtualized grid
                      </p>
                    </div>
                  </div>

                  <Suspense
                    fallback={
                      <div className="h-64 flex items-center justify-center rounded-lg border border-hairline bg-card text-xs text-muted">
                        <Loader2 className="w-4 h-4 animate-spin mr-2" />
                        <span>Loading AG Grid…</span>
                      </div>
                    }
                  >
                    <CaseGrid
                      cases={cases}
                      loading={loadingCases}
                      onRowClick={openDrawer}
                      showFilterTabs={true}
                      defaultStatusFilter={escalatedCases.length > 0 ? 'escalated' : 'all'}
                    />
                  </Suspense>
                </div>
              )}

              {/* VIEW 3: AGENT LAB */}
              {activeView === 'agent-lab' && (
                <div>
                  <AgentLab />
                </div>
              )}

              {/* VIEW 4: ANALYTICS (POWERED BY AG CHARTS) */}
              {activeView === 'analytics' && (
                <div>
                  <Suspense
                    fallback={
                      <div className="h-64 flex items-center justify-center rounded-lg border border-hairline bg-card text-xs text-muted">
                        <Loader2 className="w-4 h-4 animate-spin mr-2" />
                        <span>Loading AG Charts…</span>
                      </div>
                    }
                  >
                    <VizStudio cases={cases} />
                  </Suspense>
                </div>
              )}
            </div>
          </main>
        </div>

        {/* Case Drawer */}
        <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
          <SheetContent
            side="right"
            showCloseButton={false}
            className="bg-card border-l border-hairline text-primary flex flex-col p-0 transition-none"
            style={{ width: `${drawerWidth}px`, maxWidth: '95vw' }}
          >
            <CaseDrawer
              caseId={selectedCaseId}
              open={drawerOpen}
              onClose={() => setDrawerOpen(false)}
              onAction={refreshData}
              width={drawerWidth}
              onResize={setDrawerWidth}
            />
          </SheetContent>
        </Sheet>
      </div>
    </TooltipProvider>
  )
}
