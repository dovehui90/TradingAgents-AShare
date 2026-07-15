import { Search, X, RotateCcw } from 'lucide-react'
import type { ScreenerFilter as SFilter } from '@/types'

const POSITION_OPTIONS = [
    { value: 'overbought', label: '超买' },
    { value: 'high', label: '偏高' },
    { value: 'neutral', label: '中性' },
    { value: 'low', label: '偏低' },
    { value: 'oversold', label: '超卖' },
]
const GS_OPTIONS = ['G', 'S', 'G_zone', 'S_zone'] as const
const GS_LABELS: Record<string, string> = {
    G: 'G信号发出', S: 'S信号发出', G_zone: 'G信号+G区间', S_zone: 'S信号+S区间',
}
const ORBIT_OPTIONS = [
    { value: 'cross_up', label: '刚站上轨道线' },
    { value: 'above2', label: '持续在轨道线上方(≥2天)' },
    { value: 'cross_down', label: '刚跌破轨道线下方' },
    { value: 'below2', label: '持续在轨道线下方(≥2天)' },
]
const DECISION_OPTIONS = ['above', 'below'] as const
const DECISION_LABELS: Record<string, string> = { above: '在决策线上方', below: '在决策线下方' }
const BULL_OPTIONS = ['above', 'below'] as const
const BULL_LABELS: Record<string, string> = { above: '在牛熊线上方', below: '在牛熊线下方' }
const TREND_OPTIONS = [
    { value: 'to_red', label: '刚由绿翻红' },
    { value: 'to_green', label: '刚由红翻绿' },
    { value: 'red_hold', label: '持红(≥2天)' },
    { value: 'green_hold', label: '持绿(≥2天)' },
]

interface Props {
    filter: SFilter
    onChange: (f: SFilter) => void
    onSearch: () => void
    onClear: () => void
    loading: boolean
}

export default function ScreenerFilter({ filter, onChange, onSearch, onClear, loading }: Props) {
    const up = (s: string) => onChange({ ...filter, [s]: undefined })
    const set = (k: string, v: any) => onChange({ ...filter, [k]: v })

    const toggleMulti = (key: 'position_zones' | 'orbit_status', val: string) => {
        const cur = (filter[key] as string[]) || []
        const next = cur.includes(val) ? cur.filter(v => v !== val) : [...cur, val]
        set(key, next.length ? next : undefined)
    }

    return (
        <div className="space-y-4">
            {/* Date */}
            <div>
                <label className="text-xs font-medium text-slate-500 dark:text-slate-400">日期</label>
                <input type="date" value={filter.date || ''}
                    onChange={e => set('date', e.target.value || undefined)}
                    className="mt-1 w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-1.5 text-sm" />
            </div>

            {/* Market Cap */}
            <div>
                <label className="text-xs font-medium text-slate-500 dark:text-slate-400">流通市值（亿）</label>
                <div className="flex gap-2 mt-1">
                    <input type="number" placeholder="最小值" value={filter.market_cap_min ?? ''}
                        onChange={e => set('market_cap_min', e.target.value ? Number(e.target.value) : null)}
                        className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-1.5 text-sm" />
                    <span className="text-slate-400 self-center">—</span>
                    <input type="number" placeholder="最大值" value={filter.market_cap_max ?? ''}
                        onChange={e => set('market_cap_max', e.target.value ? Number(e.target.value) : null)}
                        className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-1.5 text-sm" />
                </div>
            </div>

            {/* Position */}
            <div>
                <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-slate-500 dark:text-slate-400">位置指标</label>
                    {filter.position_zones?.length ? <X className="w-3 h-3 text-slate-400 cursor-pointer" onClick={() => up('position_zones')} /> : null}
                </div>
                <div className="flex flex-wrap gap-1.5 mt-1">
                    {POSITION_OPTIONS.map(o => {
                        const active = (filter.position_zones || []).includes(o.value)
                        return <button key={o.value}
                            className={`text-xs px-2 py-1 rounded-full border ${active ? 'bg-purple-100 border-purple-300 text-purple-700 dark:bg-purple-900 dark:text-purple-300' : 'border-slate-200 dark:border-slate-700 text-slate-500'}`}
                            onClick={() => toggleMulti('position_zones', o.value)}>{o.label}</button>
                    })}
                </div>
            </div>

            {/* GS Signal */}
            <div>
                <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-slate-500 dark:text-slate-400">GS信号</label>
                    {filter.gs_signal ? <X className="w-3 h-3 text-slate-400 cursor-pointer" onClick={() => up('gs_signal')} /> : null}
                </div>
                <div className="flex flex-wrap gap-1.5 mt-1">
                    {GS_OPTIONS.map(o => {
                        const active = filter.gs_signal === o
                        return <button key={o}
                            className={`text-xs px-2 py-1 rounded-full border ${active ? 'bg-red-100 border-red-300 text-red-700 dark:bg-red-900 dark:text-red-300' : 'border-slate-200 dark:border-slate-700 text-slate-500'}`}
                            onClick={() => set('gs_signal', active ? undefined : o)}>{GS_LABELS[o]}</button>
                    })}
                </div>
            </div>

            {/* Orbit */}
            <div>
                <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-slate-500 dark:text-slate-400">轨道线</label>
                    {filter.orbit_status?.length ? <X className="w-3 h-3 text-slate-400 cursor-pointer" onClick={() => up('orbit_status')} /> : null}
                </div>
                <div className="flex flex-wrap gap-1.5 mt-1">
                    {ORBIT_OPTIONS.map(o => {
                        const active = (filter.orbit_status || []).includes(o.value)
                        return <button key={o.value}
                            className={`text-xs px-2 py-1 rounded-full border ${active ? 'bg-cyan-100 border-cyan-300 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300' : 'border-slate-200 dark:border-slate-700 text-slate-500'}`}
                            onClick={() => toggleMulti('orbit_status', o.value)}>{o.label}</button>
                    })}
                </div>
            </div>

            {/* Decision Line */}
            <div>
                <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-slate-500 dark:text-slate-400">决策线</label>
                    {filter.decision_status ? <X className="w-3 h-3 text-slate-400 cursor-pointer" onClick={() => up('decision_status')} /> : null}
                </div>
                <div className="flex gap-1.5 mt-1">
                    {DECISION_OPTIONS.map(o => {
                        const active = filter.decision_status === o
                        return <button key={o}
                            className={`text-xs px-2 py-1 rounded-full border ${active ? 'bg-amber-100 border-amber-300 text-amber-700 dark:bg-amber-900 dark:text-amber-300' : 'border-slate-200 dark:border-slate-700 text-slate-500'}`}
                            onClick={() => set('decision_status', active ? undefined : o)}>{DECISION_LABELS[o]}</button>
                    })}
                </div>
            </div>

            {/* Bull Line */}
            <div>
                <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-slate-500 dark:text-slate-400">牛熊线</label>
                    {filter.bull_status ? <X className="w-3 h-3 text-slate-400 cursor-pointer" onClick={() => up('bull_status')} /> : null}
                </div>
                <div className="flex gap-1.5 mt-1">
                    {BULL_OPTIONS.map(o => {
                        const active = filter.bull_status === o
                        return <button key={o}
                            className={`text-xs px-2 py-1 rounded-full border ${active ? 'bg-orange-100 border-orange-300 text-orange-700 dark:bg-orange-900 dark:text-orange-300' : 'border-slate-200 dark:border-slate-700 text-slate-500'}`}
                            onClick={() => set('bull_status', active ? undefined : o)}>{BULL_LABELS[o]}</button>
                    })}
                </div>
            </div>

            {/* Trend Strength */}
            <div>
                <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-slate-500 dark:text-slate-400">中线趋势</label>
                    {filter.trend_status ? <X className="w-3 h-3 text-slate-400 cursor-pointer" onClick={() => up('trend_status')} /> : null}
                </div>
                <div className="flex flex-wrap gap-1.5 mt-1">
                    {TREND_OPTIONS.map(o => {
                        const active = filter.trend_status === o.value
                        return <button key={o.value}
                            className={`text-xs px-2 py-1 rounded-full border ${active ? 'bg-emerald-100 border-emerald-300 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300' : 'border-slate-200 dark:border-slate-700 text-slate-500'}`}
                            onClick={() => set('trend_status', active ? undefined : o.value)}>{o.label}</button>
                    })}
                </div>
            </div>

            {/* Radar Wave */}
            <div>
                <label className="text-xs font-medium text-slate-500 dark:text-slate-400">波动线范围</label>
                <div className="flex gap-2 mt-1">
                    <input type="number" step="0.1" placeholder="min" value={filter.radar_wave_min ?? ''}
                        onChange={e => set('radar_wave_min', e.target.value ? Number(e.target.value) : null)}
                        className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-1.5 text-sm" />
                    <input type="number" step="0.1" placeholder="max" value={filter.radar_wave_max ?? ''}
                        onChange={e => set('radar_wave_max', e.target.value ? Number(e.target.value) : null)}
                        className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-1.5 text-sm" />
                </div>
            </div>

            {/* Buttons */}
            <div className="flex gap-2 pt-2">
                <button onClick={onSearch} disabled={loading || !filter.date}
                    className="flex-1 flex items-center justify-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50">
                    <Search className="w-3.5 h-3.5" />
                    开始筛选
                </button>
                <button onClick={onClear}
                    className="rounded-xl border border-slate-200 dark:border-slate-700 px-3 py-2 text-sm text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
                    <RotateCcw className="w-3.5 h-3.5" />
                </button>
            </div>
        </div>
    )
}
