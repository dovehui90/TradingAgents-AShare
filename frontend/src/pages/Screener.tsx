import { useMemo, useState } from 'react'
import { SlidersHorizontal } from 'lucide-react'
import ScreenerFilterPanel from '@/components/ScreenerFilter'
import ScreenerTable from '@/components/ScreenerTable'
import { api } from '@/services/api'
import { useScreenerStore } from '@/stores/screenerStore'
import type { ScreenerFilter, ScreenerResultItem } from '@/types'

function matchFilter(r: ScreenerResultItem, f: ScreenerFilter): boolean {
    if (f.position_zones && f.position_zones.length > 0) {
        if (!r.position_zone || !f.position_zones.includes(r.position_zone)) return false
    }
    if (f.gs_signal) {
        const gs = r.gs_status
        if (f.gs_signal === 'G_zone' && gs !== 'G' && gs !== 'G_zone') return false
        else if (f.gs_signal === 'S_zone' && gs !== 'S' && gs !== 'S_zone') return false
        else if (gs !== f.gs_signal) return false
    }
    if (f.orbit_status && f.orbit_status.length > 0) {
        if (!r.orbit_status || !f.orbit_status.includes(r.orbit_status)) return false
    }
    if (f.decision_status && r.decision_status !== f.decision_status) return false
    if (f.bull_status && r.bull_status !== f.bull_status) return false
    if (f.trend_status && r.trend_status !== f.trend_status) return false
    if (f.radar_wave_min != null && (r.radar_wave == null || r.radar_wave < f.radar_wave_min)) return false
    if (f.radar_wave_max != null && (r.radar_wave == null || r.radar_wave > f.radar_wave_max)) return false
    return true
}

export default function Screener() {
    const storeFilter = useScreenerStore(s => s.filter)
    const allResults = useScreenerStore(s => s.allResults)
    const serverCandidates = useScreenerStore(s => s.totalCandidates)
    const serverElapsed = useScreenerStore(s => s.elapsedMs)
    const dataDate = useScreenerStore(s => s.dataDate)
    const setFilterStore = useScreenerStore(s => s.setFilter)
    const setResultsStore = useScreenerStore(s => s.setResults)
    const clearResultsStore = useScreenerStore(s => s.clearResults)

    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')

    const filteredResults = useMemo(() => {
        return allResults.filter(r => matchFilter(r, storeFilter))
    }, [allResults, storeFilter])

    const handleSearch = async () => {
        if (!storeFilter.date) {
            setError('请先选择日期')
            return
        }
        setLoading(true)
        setError('')
        try {
            const req: ScreenerFilter = {}
            if (storeFilter.market_cap_min != null || storeFilter.market_cap_max != null) {
                req.market_cap_min = storeFilter.market_cap_min
                req.market_cap_max = storeFilter.market_cap_max
            }
            const resp = await api.screener(req as ScreenerFilter)
            setResultsStore(resp.results, resp.total_candidates, resp.elapsed_ms, resp.data_date)
        } catch (e: any) {
            setError(e?.message || '筛选失败，请检查网络或筛选条件')
        } finally {
            setLoading(false)
        }
    }

    const handleClear = () => {
        setFilterStore({})
        clearResultsStore()
        setError('')
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <SlidersHorizontal className="w-5 h-5 text-blue-500" />
                <h1 className="text-lg font-semibold text-slate-800 dark:text-slate-200">选股神器</h1>
            </div>

            <div className="flex flex-col lg:flex-row gap-4">
                <div className="lg:w-64 shrink-0">
                    <div className="card lg:sticky lg:top-20 max-h-none lg:max-h-[calc(100vh-8rem)] overflow-y-auto">
                        <ScreenerFilterPanel
                            filter={storeFilter}
                            onChange={setFilterStore}
                            onSearch={handleSearch}
                            onClear={handleClear}
                            loading={loading}
                        />
                    </div>
                </div>

                <div className="flex-1 min-w-0">
                    {loading && (
                        <div className="card flex items-center justify-center py-16">
                            <div className="flex flex-col items-center gap-2">
                                <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                                <span className="text-sm text-slate-500">正在计算指标...</span>
                            </div>
                        </div>
                    )}

                    {error && (
                        <div className="card text-center py-8 text-red-500">{error}</div>
                    )}

                    {!loading && !error && allResults.length === 0 && (
                        <div className="card text-center py-16 text-slate-400 dark:text-slate-500">
                            <SlidersHorizontal className="w-12 h-12 mx-auto mb-3 opacity-30" />
                            <div>设置市值范围后点击"开始筛选"</div>
                        </div>
                    )}

                    {!loading && allResults.length > 0 && (
                        <ScreenerTable
                            results={filteredResults}
                            totalCandidates={serverCandidates}
                            totalFiltered={filteredResults.length}
                            elapsedMs={serverElapsed}
                            dataDate={dataDate}
                        />
                    )}
                </div>
            </div>
        </div>
    )
}
