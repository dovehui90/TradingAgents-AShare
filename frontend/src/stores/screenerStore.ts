import { create } from 'zustand'
import type { ScreenerFilter, ScreenerResultItem } from '@/types'

interface ScreenerState {
    filter: ScreenerFilter
    allResults: ScreenerResultItem[]
    totalCandidates: number
    elapsedMs: number
    dataDate: string | null
    setFilter: (f: ScreenerFilter) => void
    setResults: (results: ScreenerResultItem[], candidates: number, elapsed: number, dataDate: string | null) => void
    clearResults: () => void
}

export const useScreenerStore = create<ScreenerState>()((set) => ({
    filter: {},
    allResults: [],
    totalCandidates: 0,
    elapsedMs: 0,
    dataDate: null,
    setFilter: (filter) => set({ filter }),
    setResults: (allResults, totalCandidates, elapsedMs, dataDate) =>
        set({ allResults, totalCandidates, elapsedMs, dataDate }),
    clearResults: () => set({ allResults: [], totalCandidates: 0, elapsedMs: 0, dataDate: null }),
}))
