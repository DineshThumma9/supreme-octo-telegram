import { useEffect, useState } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'

import { StatsBar } from './components/StatsBar'
import { EscalationPanel } from './components/EscalationPanel'
import { CaseTable } from './components/CaseTable'
import { CaseDrawer } from './components/CaseDrawer'

import { 
    Sheet, 
    SheetContent
} from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { fetchCase, simulateFire, simulateAction, clearAllCases } from "./api"
import { useCaseStore } from "./store/useCaseStore"
import type { Case } from "./types"
import { 
    Send, 
    Loader2, 
    FastForward, 
    MessageSquare, 
    CreditCard, 
    Play, 
    RotateCcw,
    X
} from "lucide-react"

interface ChatMessage {
    id: string
    sender: 'user' | 'agent' | 'system'
    text: string
    timestamp: Date
    isStatus?: boolean
    channel?: 'whatsapp' | 'email' | 'system'
}

function buildChatFromAuditLog(caseData: Case): ChatMessage[] {
    const msgs: ChatMessage[] = []
    
    msgs.push({
        id: `init-${caseData.case_id}`,
        sender: 'system',
        text: `Payment failure detected: $${(caseData.amount || 0).toLocaleString()} (${caseData.failure_reason || 'Declined'})`,
        timestamp: caseData.first_seen_at ? new Date(caseData.first_seen_at) : new Date(),
        isStatus: true,
        channel: 'system',
    })

    if (caseData.audit_log && caseData.audit_log.length > 0) {
        caseData.audit_log.forEach((log, i) => {
            if (log.event_triggered === 'payment_failed') return

            const nextStr = log.next_contact ? ` · Next scheduled: ${new Date(log.next_contact).toLocaleDateString()}` : ''
            const text = (log.message || `Agent action: ${log.event_triggered.replace(/_/g, ' ')}`) + nextStr
            const isCust = log.direction === 'inbound' || log.event_triggered === 'customer_reply'
            const isSys = log.direction === 'system' || ['get_next_payday_date', 'log_promise_to_pay'].includes(log.event_triggered)
            
            msgs.push({
                id: `log-${caseData.case_id}-${i}-${log.event_triggered}`,
                sender: isCust ? 'user' : isSys ? 'system' : 'agent',
                text,
                timestamp: log.created_at ? new Date(log.created_at) : new Date(),
                isStatus: isSys,
                channel: (log.channel as any) || (isSys ? 'system' : 'whatsapp')
            })
        })
    }

    if (['recovered', 'closed', 'escalated'].includes(caseData.recovery_status)) {
        const terminalMsg = caseData.recovery_status === 'escalated'
            ? `Case escalated to human support (Attempt count: ${caseData.attempt_count}/3).`
            : `Case resolved and marked as ${caseData.recovery_status.toUpperCase()}.`
        msgs.push({
            id: `term-${caseData.case_id}`,
            sender: 'system',
            text: terminalMsg,
            timestamp: new Date(),
            isStatus: true,
            channel: 'system',
        })
    }

    return msgs
}

export default function App() {
  const [drawerWidth, setDrawerWidth] = useState(720)

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
  const [simulate,onSimulate] = useState<boolean>(false);


   const [step, setStep] = useState<1 | 2>(1)
      const [isSimulating, setIsSimulating] = useState(false)
      const [isPolling, setIsPolling] = useState(false)
      
      const [eventType, setEventType] = useState("order.failed")
      const [declineReason, setDeclineReason] = useState("Insufficient funds")
  
      const handleScenarioChange = (val: string) => {
          setEventType(val)
          if (val === "order.failed") setDeclineReason("Insufficient funds")
          else if (val === "subscription_failed") setDeclineReason("Mandate auto-debit failed")
          else if (val === "invoice_failed") setDeclineReason("Invoice overdue")
      }
      const [amount, setAmount] = useState(480)
      const [name, setName] = useState("Alex Morgan")
      const [email, setEmail] = useState("test@example.com")
      const [phone, setPhone] = useState("+14155550123")
      const [resumeCaseId, setResumeCaseId] = useState("")
  
      // Step 2 Simulation Data
      const [activeCaseId, setActiveCaseId] = useState<string | null>(null)
      const [activeCase, setActiveCase] = useState<Case | null>(null)
      const [chatHistory, setChatHistory] = useState<ChatMessage[]>([])
      const [replyText, setReplyText] = useState("")
  
      // Live real-time sync with Zustand store when SSE events update active case
      const storeCase = useCaseStore(state => state.cases.find(c => c.case_id === activeCaseId))
  
      useEffect(() => {
          if (storeCase && activeCaseId) {
              setActiveCase(storeCase)
              setChatHistory(buildChatFromAuditLog(storeCase))
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
          setChatHistory([])
          setReplyText("")
          setResumeCaseId("")
      }

      const handleResumeEvent = async () => {
          const targetId = resumeCaseId.trim()
          if (!targetId) return
          setIsSimulating(true)
          try {
              const caseData = await fetchCase(targetId)
              if (caseData) {
                  setActiveCaseId(caseData.case_id)
                  setActiveCase(caseData)
                  setName(caseData.customer.name || name)
                  setAmount(caseData.amount || amount)
                  setChatHistory(buildChatFromAuditLog(caseData))
                  setStep(2)
                  setIsPolling(true)
              }
          } catch (error) {
              console.error("Failed to resume case", error)
          } finally {
              setIsSimulating(false)
          }
      }
  
      const handleFireEvent = async (e?: React.FormEvent) => {
          if (e) e.preventDefault()
          if (resumeCaseId.trim()) {
              return handleResumeEvent()
          }
          setIsSimulating(true)
  
          const payload = {
              event_type: eventType,
              decline_reason: declineReason,
              amount: Number(amount),
              name: name || "Dinesh",
              email: email || "test@example.com",
              phone: phone || "+14155550123",
          }
  
          try {
            const data = await simulateFire(payload)
            
            if (data.id) {
                setActiveCaseId(data.id)
                setChatHistory([
                    {
                        id: `init-${data.id}`,
                        sender: 'system',
                        text: `Payment failure detected: $${amount.toLocaleString()} (${declineReason})`,
                        timestamp: new Date(),
                        isStatus: true
                    }
                ])
                setStep(2)
                setIsPolling(true)
            }
        } catch (error) {
            console.error("Simulation trigger failed", error)
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
            setChatHistory(buildChatFromAuditLog(caseData))

            if (caseData.recovery_status === "recovered" || caseData.recovery_status === "closed" || caseData.recovery_status === "escalated") {
                setIsPolling(false)
            }
        } catch (error) {
            console.error("Poll failed", error)
        }
    }

    const handleAction = async (actionType: 'pay' | 'ignore' | 'reply', msgContent?: string) => {
        if (!activeCaseId) return
        setIsSimulating(true)

        if (actionType === 'reply' && msgContent) {
            setChatHistory(prev => [...prev, {
                id: `pending-${Date.now()}`,
                sender: 'user',
                text: msgContent,
                timestamp: new Date(),
                channel: 'whatsapp'
            }])
            setReplyText("")
        }

        try {
            await simulateAction({
                case_id: activeCaseId,
                actions: actionType,
                messages: msgContent || "",
            })
            await pollCaseStatus()
            refreshData()
        } catch (error) {
            console.error("Action dispatch failed", error)
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
      const entry = reversed.find(l => l.next_contact)
      if (entry?.next_contact) return entry.next_contact
    }
    return null
  })()

  const latestAgentMessage = (() => {
    if (activeCase?.audit_log && activeCase.audit_log.length > 0) {
      const reversed = [...activeCase.audit_log].reverse()
      const lastOutbound = reversed.find(l => 
        l.direction === 'outbound' || 
        l.channel === 'whatsapp' || 
        l.event_triggered.startsWith('send_') || 
        l.event_triggered.startsWith('create_')
      )
      if (lastOutbound?.message) {
        const nextStr = lastOutbound.next_contact ? ` · Next scheduled: ${new Date(lastOutbound.next_contact).toLocaleDateString()}` : ''
        return lastOutbound.message + nextStr
      }
    }
    const agentMsgs = chatHistory.filter(m => m.sender === 'agent')
    if (agentMsgs.length > 0) return agentMsgs[agentMsgs.length - 1].text
    return `Hi ${name}, looks like your payment of $${amount.toLocaleString()} didn't go through due to a temporary PayPal issue. Your order is reserved. Tap the link to retry.`
  })()

  return (
    <TooltipProvider delay={0}>
      <div className="flex flex-col h-screen overflow-hidden bg-[#0a0a0c] text-zinc-300 font-sans selection:bg-indigo-500/30">
        
        {/* Header (Top Navigation) */}
        <header className="bg-[#09090d]/80 backdrop-blur sticky top-0 z-40 shrink-0 border-b border-zinc-800/60">
          <div className="max-w-screen-xl mx-auto px-6 h-14 flex items-center justify-between gap-6">
            <div className="flex items-center gap-2">
              <svg className="w-5 h-5 text-violet-500" viewBox="0 0 24 24" fill="currentColor">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
              </svg>
              <span className="font-semibold text-zinc-100 tracking-tight">Renvue</span>
              <span className="text-zinc-700 mx-1">·</span>
              <span className="text-xs text-zinc-500">Recovery Ops</span>
            </div>

            <div className="flex items-center gap-2.5">
              {/* Sandbox Mode Badge */}


              {/* Live SSE Stream Connection Badge */}
              <div className="flex items-center gap-2 px-2.5 py-1 rounded-full bg-zinc-900/90 border border-zinc-800">
                <span className="relative flex h-2 w-2">
                  {sseConnected && (
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  )}
                  <span className={`relative inline-flex rounded-full h-2 w-2 ${sseConnected ? 'bg-emerald-500' : 'bg-amber-500'}`}></span>
                </span>
                <span className="text-[11px] font-medium tracking-tight text-zinc-400">
                  {sseConnected ? 'LIVE SSE' : 'CONNECTING...'}
                </span>
              </div>
            </div>
          </div>
        </header>

        {/* Main Content */}
        <div className="flex-1 overflow-y-auto">
          <main className="max-w-screen-xl mx-auto px-6 py-8">
            <div className="flex w-full justify-end mb-6 gap-3">
              <Button 
                variant="outline" 
                onClick={async () => {
                   if(confirm('Are you sure you want to clear all cases?')) {
                       await clearAllCases();
                       refreshData();
                   }
                }}
                className="bg-red-950/20 border-red-900/50 text-red-500 hover:bg-red-900/40 hover:text-red-400"
              >
                Clear All Cases
              </Button>
              <Button
                onClick={() => onSimulate(!simulate)}
                className="bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs h-9 px-4 rounded-lg shadow-sm transition-all flex items-center gap-2"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                {simulate ? "Close Testbench" : "Simulate Failure"}
              </Button>
            </div>
            
            <StatsBar stats={stats} loading={loadingStats} />

            {/* Ultra-Clean Simulation Testbench */}
            {simulate && (
              <div className="mb-8 rounded-xl border border-zinc-800/80 bg-[#0d0d12] p-5 shadow-2xl transition-all">
                {step === 1 ? (
                  /* Step 1: Concise Failure Scenario Selection & Trigger */
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                        Select Scenario
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onSimulate(false)}
                        className="text-xs text-zinc-500 hover:text-zinc-300 h-6 px-2"
                      >
                        <X className="w-3.5 h-3.5" />
                      </Button>
                    </div>

                    <RadioGroup value={eventType} onValueChange={handleScenarioChange} className="grid grid-cols-1 md:grid-cols-4 gap-3">
                      <label htmlFor="sc-soft" className="border border-zinc-800 bg-zinc-900/40 hover:bg-zinc-900 hover:border-zinc-700 rounded-xl cursor-pointer transition-all has-[[data-checked]]:border-indigo-500/60 has-[[data-checked]]:bg-indigo-500/10 block">
                        <div className="p-3 w-full justify-between items-center flex">
                          <div>
                            <div className="text-xs font-semibold text-zinc-100">Soft Decline</div>
                            <p className="text-[11px] text-zinc-400 mt-0.5">Insufficient funds retry</p>
                          </div>
                          <RadioGroupItem value="order.failed" id="sc-soft" className="border-zinc-600 text-indigo-500 h-3.5 w-3.5" />
                        </div>
                      </label>

                      <label htmlFor="sc-sub" className="border border-zinc-800 bg-zinc-900/40 hover:bg-zinc-900 hover:border-zinc-700 rounded-xl cursor-pointer transition-all has-[[data-checked]]:border-indigo-500/60 has-[[data-checked]]:bg-indigo-500/10 block">
                        <div className="p-3 w-full justify-between items-center flex">
                          <div>
                            <div className="text-xs font-semibold text-zinc-100">Subscription Failure</div>
                            <p className="text-[11px] text-zinc-400 mt-0.5">Recurring billing failure</p>
                          </div>
                          <RadioGroupItem value="subscription_failed" id="sc-sub" className="border-zinc-600 text-indigo-500 h-3.5 w-3.5" />
                        </div>
                      </label>

                      <label htmlFor="sc-invoice" className="border border-zinc-800 bg-zinc-900/40 hover:bg-zinc-900 hover:border-zinc-700 rounded-xl cursor-pointer transition-all has-[[data-checked]]:border-indigo-500/60 has-[[data-checked]]:bg-indigo-500/10 block">
                        <div className="p-3 w-full justify-between items-center flex">
                          <div>
                            <div className="text-xs font-semibold text-zinc-100">Overdue Invoice</div>
                            <p className="text-[11px] text-zinc-400 mt-0.5">PayPal invoice reminder</p>
                          </div>
                          <RadioGroupItem value="invoice_failed" id="sc-invoice" className="border-zinc-600 text-indigo-500 h-3.5 w-3.5" />
                        </div>
                      </label>

                      <label htmlFor="sc-cart" className="border border-zinc-800 bg-zinc-900/40 hover:bg-zinc-900 hover:border-zinc-700 rounded-xl cursor-pointer transition-all has-[[data-checked]]:border-indigo-500/60 has-[[data-checked]]:bg-indigo-500/10 block">
                        <div className="p-3 w-full justify-between items-center flex">
                          <div>
                            <div className="text-xs font-semibold text-zinc-100">Abandoned Checkout</div>
                            <p className="text-[11px] text-zinc-400 mt-0.5">Reserved discount recovery</p>
                          </div>
                          <RadioGroupItem value="abandoned_checkout" id="sc-cart" className="border-zinc-600 text-indigo-500 h-3.5 w-3.5" />
                        </div>
                      </label>
                    </RadioGroup>

                    {/* Horizontal Inputs Grid with Labels */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3 pt-3 border-t border-zinc-800/60">
                      <div className="space-y-1.5">
                        <Label className="text-[11px] font-medium text-zinc-400">Customer Name</Label>
                        <Input
                          value={name}
                          onChange={e => setName(e.target.value)}
                          placeholder="e.g. Dinesh"
                          className="bg-zinc-900 border-zinc-800 text-zinc-100 h-8 text-xs"
                        />
                      </div>

                      <div className="space-y-1.5">
                        <Label className="text-[11px] font-medium text-zinc-400">Amount (USD)</Label>
                        <Input
                          type="number"
                          value={amount}
                          onChange={e => setAmount(Number(e.target.value))}
                          placeholder="5000"
                          className="bg-zinc-900 border-zinc-800 text-zinc-100 font-medium h-8 text-xs"
                        />
                      </div>

                      <div className="space-y-1.5">
                        <Label className="text-[11px] font-medium text-zinc-400">WhatsApp / Phone</Label>
                        <Input
                          value={phone}
                          onChange={e => setPhone(e.target.value)}
                          placeholder="+14155550123"
                          className="bg-zinc-900 border-zinc-800 text-zinc-100 h-8 text-xs"
                        />
                      </div>

                      <div className="space-y-1.5">
                        <Label className="text-[11px] font-medium text-zinc-400">Email Address</Label>
                        <Input
                          value={email}
                          onChange={e => setEmail(e.target.value)}
                          placeholder="name@example.com"
                          className="bg-zinc-900 border-zinc-800 text-zinc-100 h-8 text-xs"
                        />
                      </div>

                      <div className="space-y-1.5">
                        <Label className="text-[11px] font-medium text-zinc-400">Prev Case ID</Label>
                        <Input
                          value={resumeCaseId}
                          onChange={e => setResumeCaseId(e.target.value)}
                          placeholder="pay_fail_... (optional)"
                          className="bg-zinc-900 border-zinc-800 text-zinc-100 h-8 text-xs"
                        />
                      </div>
                    </div>

                    <div className="flex justify-end pt-1">
                      <Button 
                        onClick={handleFireEvent} 
                        disabled={isSimulating}
                        className="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold h-8 px-5 shadow-sm"
                      >
                        {isSimulating ? (
                          <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> {resumeCaseId.trim() ? "Resuming..." : "Launching..."}</>
                        ) : (
                          resumeCaseId.trim() ? "Follow Up Case" : "Run Scenario"
                        )}
                      </Button>
                    </div>
                  </div>
                ) : (
                  /* Step 2: Ultra-Clean WhatsApp Bubble + 3 Options (No Header/Footer Clutter) */
                  <div className="space-y-3">
                    {/* Agent WhatsApp Outreach Message */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="max-w-2xl bg-[#0b3328] border border-emerald-700/40 text-emerald-50 rounded-2xl rounded-tl-sm px-4 py-2.5 text-xs shadow-sm leading-relaxed">
                        <div className="text-[10px] font-medium text-emerald-400 mb-1 flex items-center gap-1.5">
                          <MessageSquare className="w-3 h-3" /> WhatsApp to {name} · ${amount.toLocaleString()}
                        </div>
                        <p className="text-xs text-emerald-50 leading-relaxed whitespace-pre-wrap">
                          {latestAgentMessage}
                        </p>
                      </div>

                      <div className="flex items-center gap-1 shrink-0">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={resetState}
                          className="text-xs text-zinc-500 hover:text-zinc-200 h-7 px-2"
                          title="Reset to New Run"
                        >
                          <RotateCcw className="w-3.5 h-3.5 mr-1" /> New
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => onSimulate(false)}
                          className="text-xs text-zinc-500 hover:text-zinc-200 h-7 px-1.5"
                        >
                          <X className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </div>

                    {/* Live Progress & Next Scheduled Telemetry Bar */}
                    <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-[11px] text-zinc-400">
                      <div className="flex items-center gap-2">
                        <span className="text-zinc-500">Next Scheduled:</span>
                        <span className="text-emerald-400 font-medium">
                          {activeCase?.next_retry_at 
                            ? new Date(activeCase.next_retry_at).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
                            : (latestNextContact 
                                ? new Date(latestNextContact).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
                                : 'None scheduled')}
                        </span>
                        <span className="text-zinc-600">·</span>
                        <span className="text-zinc-400">
                          Attempt: <strong className="text-zinc-200">{activeCase?.attempt_count ?? 1}/3</strong>
                        </span>
                      </div>

                      {activeCaseId && (
                        <div className="flex items-center gap-1 text-[11px] text-zinc-500 font-normal">
                          <span>Case ID: {activeCaseId}</span>
                        </div>
                      )}
                    </div>

                    {/* 3 Options: Ignore (+3 Days), Settle Payment, Reply */}
                    {activeCase && ['recovered', 'closed', 'escalated'].includes(activeCase.recovery_status) ? (
                      <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-900 border border-zinc-800 text-xs">
                        <span className="text-zinc-200">
                          {activeCase.recovery_status === 'escalated'
                            ? `⚠️ Case escalated to human support (Attempt ${activeCase.attempt_count}/3).`
                            : `✅ Payment resolved and marked as ${activeCase.recovery_status.toUpperCase()}.`}
                        </span>
                        <Button size="sm" onClick={resetState} className="bg-indigo-600 hover:bg-indigo-500 h-7 text-xs">
                          New Run
                        </Button>
                      </div>
                    ) : (
                      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 pt-1">
                        {/* Option 1: Ignore (+3 Days) */}
                        <Button 
                          size="sm" 
                          variant="outline" 
                          className="bg-zinc-900 border-zinc-800 hover:bg-zinc-800 text-zinc-200 text-xs h-9 font-medium shrink-0"
                          onClick={() => handleAction('ignore')}
                          disabled={isSimulating}
                          title="Simulate customer ignoring message; fast-forwards to next attempt"
                        >
                          {isSimulating ? (
                            <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                          ) : (
                            <FastForward className="w-3.5 h-3.5 mr-1.5 text-indigo-400" />
                          )}
                          Fast-Forward (+3 Days)
                        </Button>

                        {/* Option 2: Settle Payment */}
                        <Button 
                          size="sm" 
                          variant="outline" 
                          className="bg-zinc-900 border-zinc-800 hover:bg-zinc-800 text-emerald-400 hover:text-emerald-300 text-xs h-9 font-medium shrink-0"
                          onClick={() => handleAction('pay')}
                          disabled={isSimulating}
                        >
                          <CreditCard className="w-3.5 h-3.5 mr-1.5" />
                          Settle Payment
                        </Button>

                        {/* Option 3: WhatsApp chatapp style single-span reply input */}
                        <form 
                          className="flex-1 flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 rounded-lg px-2 py-0.5 focus-within:border-emerald-500/70"
                          onSubmit={(e) => {
                            e.preventDefault()
                            if (replyText.trim()) handleAction('reply', replyText)
                          }}
                        >
                          <Input 
                            value={replyText}
                            onChange={e => setReplyText(e.target.value)}
                            placeholder="Type customer WhatsApp reply..." 
                            className="bg-transparent border-0 focus-visible:ring-0 text-zinc-100 h-8 text-xs px-1 shadow-none"
                            disabled={isSimulating}
                          />
                          <Button 
                            type="submit" 
                            size="icon" 
                            className="h-7 w-7 shrink-0 bg-emerald-600 hover:bg-emerald-500 text-white rounded-md"
                            disabled={!replyText.trim() || isSimulating}
                          >
                            {isSimulating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
                          </Button>
                        </form>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
            {/* Escalation panel */}
            <EscalationPanel
              cases={escalatedCases}
              onSelect={openDrawer}
              onApprove={refreshData}
            />

            {/* Processing Queue */}
            <div className="mb-8">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-base font-semibold text-zinc-200">Active Processing Queue</h2>
                  <p className="text-xs text-zinc-500 mt-0.5">
                    {loadingCases ? 'Loading…' : `${processingCases.length} active cases · live SSE updates`}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="border-zinc-700 bg-transparent text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 h-8 text-xs"
                  onClick={refreshData}
                >
                  Refresh
                </Button>
              </div>
              <CaseTable
                cases={processingCases}
                loading={loadingCases}
                onRowClick={openDrawer}
              />
            </div>

            {/* Success Section */}
            {recoveredCases.length > 0 && (
              <div className="mb-8">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h2 className="text-base font-semibold text-emerald-400">Successfully Recovered</h2>
                    <p className="text-xs text-zinc-500 mt-0.5">
                      {recoveredCases.length} resolved cases
                    </p>
                  </div>
                </div>
                <CaseTable
                  cases={recoveredCases}
                  loading={loadingCases}
                  onRowClick={openDrawer}
                />
              </div>
            )}
          </main>
        </div>

        {/* Case Details Slide-Over Sheet */}
        <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
          <SheetContent 
            side="right" 
            showCloseButton={false} 
            style={{ width: `${drawerWidth}px`, maxWidth: '95vw' }}
            className="bg-[#0d1117] border-l border-zinc-800 text-zinc-100 flex flex-col p-0 shadow-2xl transition-none"
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
