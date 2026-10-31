import { create } from "zustand"
import { fetchCases, fetchStats, API_BASE_URL } from "../api"
import type { Case, Stats } from "../types"

export const DEFAULT_STATS: Stats = {
  total_cases: 0,
  total_at_risk: 0,
  recovered_count: 0,
  recovered_amount: 0,
  recovery_rate_pct: 0,
  escalated_count: 0,
  still_active: 0,
}

interface CaseState {
  cases: Case[]
  stats: Stats
  loadingCases: boolean
  loadingStats: boolean
  selectedCaseId: string | null
  drawerOpen: boolean
  sseConnected: boolean

  // Actions
  setCases: (cases: Case[]) => void
  setStats: (stats: Stats) => void
  setSelectedCaseId: (id: string | null) => void
  setDrawerOpen: (open: boolean) => void
  updateOrAddCase: (updatedCase: Case) => void
  refreshData: () => Promise<void>
  initSSE: () => () => void
}

export const useCaseStore = create<CaseState>((set, get) => ({
  cases: [],
  stats: DEFAULT_STATS,
  loadingCases: false,
  loadingStats: false,
  selectedCaseId: null,
  drawerOpen: false,
  sseConnected: false,

  setCases: (cases) => set({ cases }),
  setStats: (stats) => set({ stats }),
  setSelectedCaseId: (selectedCaseId) => set({ selectedCaseId }),
  setDrawerOpen: (drawerOpen) => set({ drawerOpen }),

  updateOrAddCase: (updatedCase: Case) => {
    set((state) => {
      const idx = state.cases.findIndex((c) => c.case_id === updatedCase.case_id)
      let newCases: Case[]
      if (idx !== -1) {
        newCases = [...state.cases]
        newCases[idx] = updatedCase
      } else {
        newCases = [updatedCase, ...state.cases]
      }
      return { cases: newCases }
    })
    // Re-fetch aggregate stats in the background without clearing loading states
    fetchStats().then(s => set({ stats: s })).catch(() => {})
  },

  refreshData: async () => {
    try {
      const [casesRes, statsRes] = await Promise.allSettled([fetchCases(), fetchStats()])
      const updates: Partial<CaseState> = { loadingCases: false, loadingStats: false }
      if (casesRes.status === "fulfilled") {
        updates.cases = casesRes.value
      }
      if (statsRes.status === "fulfilled") {
        updates.stats = statsRes.value
      } else if (!get().stats) {
        updates.stats = DEFAULT_STATS
      }
      set(updates)
    } catch (err) {
      console.error("[Store] Failed to fetch data:", err)
      set((state) => ({ loadingCases: false, loadingStats: false, stats: state.stats || DEFAULT_STATS }))
    }
  },

  initSSE: () => {
    const streamUrl = `${API_BASE_URL}/stream`
    let eventSource: EventSource | null = null
    let reconnectTimeout: any = null

    const connect = () => {
      try {
        eventSource = new EventSource(streamUrl)

        eventSource.onopen = () => {
          set({ sseConnected: true })
          console.log("[SSE] Stream connected successfully")
        }

        eventSource.onmessage = (event) => {
          try {
            if (!event.data) return
            const payload = JSON.parse(event.data)
            if (payload.type === "CASE_UPDATED" && payload.data) {
              console.log("[SSE] Live case update received:", payload.data.case_id)
              get().updateOrAddCase(payload.data)
            } else if (payload.type === "STATS_UPDATED" && payload.data) {
              set({ stats: payload.data })
            }
          } catch {
            // Ignore non-json or ping frames
          }
        }

        eventSource.onerror = () => {
          set({ sseConnected: false })
          if (eventSource) {
            eventSource.close()
          }
          reconnectTimeout = setTimeout(connect, 3000)
        }
      } catch (err) {
        console.error("[SSE] Connection error:", err)
        set({ sseConnected: false })
        reconnectTimeout = setTimeout(connect, 3000)
      }
    }

    connect()

    return () => {
      if (reconnectTimeout) clearTimeout(reconnectTimeout)
      if (eventSource) eventSource.close()
      set({ sseConnected: false })
    }
  },
}))
