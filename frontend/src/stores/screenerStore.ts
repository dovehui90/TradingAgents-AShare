import { create } from 'zustand'
import type { ScreenerFilter, ScreenerResultItem } from '@/types'

interface ScreenerState {
    filter: ScreenerFilter
    allResults: ScreenerResultItem[]
    totalCandidates: number
    elapsedMs: number
    setFilter: (f: ScreenerFilter) => void
    setResults: (results: ScreenerResultItem[], candidates: number, elapsed: number) => void
    clearResults: () => void
}

export const useScreenerStore = create<ScreenerState>()((set) => ({
    filter: {},
    allResults: [],
    totalCandidates: 0,
    elapsedMs: 0,
    setFilter: (filter) => set({ filter }),
    setResults: (allResults, totalCandidates, elapsedMs) =>
        set({ allResults, totalCandidates, elapsedMs }),
    clearResults: () => set({ allResults: [], totalCandidates: 0, elapsedMs: 0 }),
}))
