import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { ScreenerResultItem } from '@/types'

const PAGE_SIZE = 20

const POSITION_LABELS: Record<string, string> = {
    overbought: '超买', high: '偏高', neutral: '中性', low: '偏低', oversold: '超卖',
}
const POSITION_COLORS: Record<string, string> = {
    overbought: 'text-red-600', high: 'text-orange-500', neutral: 'text-slate-400',
    low: 'text-blue-500', oversold: 'text-green-600',
}
const GS_LABELS: Record<string, string> = {
    G: 'G↗', S: 'S↘', G_zone: 'G区', S_zone: 'S区',
}
const GS_COLORS: Record<string, string> = {
    G: 'text-red-600', S: 'text-green-600', G_zone: 'text-red-400', S_zone: 'text-green-400',
}
const ORBIT_LABELS: Record<string, string> = {
    cross_up: '刚站上', above2: '上方≥2', cross_down: '刚跌破', below2: '下方≥2',
}
const DECISION_LABELS: Record<string, string> = { above: '上方', below: '下方' }
const BULL_LABELS: Record<string, string> = { above: '上方', below: '下方' }
const TREND_LABELS: Record<string, string> = {
    to_red: '翻红', to_green: '翻绿', red_hold: '持红', green_hold: '持绿',
}
const TREND_COLORS: Record<string, string> = {
    to_red: 'text-red-600', red_hold: 'text-red-500', to_green: 'text-green-600', green_hold: 'text-green-500',
}

interface Props {
    results: ScreenerResultItem[]
    totalCandidates: number
    totalFiltered: number
    elapsedMs: number
    dataDate: string | null
}

export default function ScreenerTable({ results, totalCandidates, totalFiltered, elapsedMs, dataDate }: Props) {
    const navigate = useNavigate()
    const [page, setPage] = useState(1)
    const totalPages = Math.max(1, Math.ceil(results.length / PAGE_SIZE))

    const pageResults = useMemo(() => {
        const start = (page - 1) * PAGE_SIZE
        return results.slice(start, start + PAGE_SIZE)
    }, [results, page])

    useEffect(() => { setPage(1) }, [results.length])

    const fmtMcap = (v: number | null) => {
        if (v == null) return '-'
        if (v >= 10000) return `${(v / 10000).toFixed(2)}万亿`
        return `${v.toFixed(0)}亿`
    }

    if (results.length === 0) {
        return (
            <div className="card text-center py-12 text-slate-400 dark:text-slate-500">
                未找到符合条件的股票，请放宽筛选条件后重试
            </div>
        )
    }

    return (
        <div>
            <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-slate-500 dark:text-slate-400">
                    符合 {totalFiltered} 只 / 候选 {totalCandidates} 只，耗时 {elapsedMs >= 1000 ? `${(elapsedMs / 1000).toFixed(1)}s` : `${elapsedMs}ms`}
                </span>
                {dataDate && (() => {
                    const [y, m, d] = dataDate.split('-')
                    return (
                        <span className="text-xs text-slate-400 dark:text-slate-500">
                            数据更新：{y}年{parseInt(m)}月{parseInt(d)}日
                        </span>
                    )
                })()}
            </div>
            <div className="card overflow-hidden p-0">
                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50">
                                <th className="px-3 py-2 text-left text-xs font-medium text-slate-500">代码</th>
                                <th className="px-3 py-2 text-left text-xs font-medium text-slate-500">名称</th>
                                <th className="px-3 py-2 text-left text-xs font-medium text-slate-500">概念板块</th>
                                <th className="px-3 py-2 text-right text-xs font-medium text-slate-500">价格</th>
                                <th className="px-3 py-2 text-right text-xs font-medium text-slate-500">涨跌</th>
                                <th className="px-3 py-2 text-right text-xs font-medium text-slate-500">流通市值</th>
                                <th className="px-3 py-2 text-center text-xs font-medium text-slate-500">位置</th>
                                <th className="px-3 py-2 text-center text-xs font-medium text-slate-500">GS</th>
                                <th className="px-3 py-2 text-center text-xs font-medium text-slate-500">轨道</th>
                                <th className="px-3 py-2 text-center text-xs font-medium text-slate-500">决策</th>
                                <th className="px-3 py-2 text-center text-xs font-medium text-slate-500">牛熊</th>
                                <th className="px-3 py-2 text-center text-xs font-medium text-slate-500">趋势</th>
                                <th className="px-3 py-2 text-right text-xs font-medium text-slate-500">主力雷达</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                            {pageResults.map(r => (
                                <tr key={r.symbol}
                                    className="hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer transition-colors"
                                    onClick={() => navigate(`/analysis?symbol=${r.symbol}&no_auto=1`)}>
                                    <td className="px-3 py-2 font-mono text-xs">{r.symbol.split('.')[0]}</td>
                                    <td className="px-3 py-2 font-medium text-slate-800 dark:text-slate-200">{r.name}</td>
                                    <td className="px-3 py-2 text-xs text-slate-500 max-w-[120px] truncate" title={r.concepts ?? undefined}>{r.concepts || '-'}</td>
                                    <td className="px-3 py-2 text-right font-mono">{r.price?.toFixed(2) ?? '-'}</td>
                                    <td className={`px-3 py-2 text-right font-mono ${r.change_pct != null ? (r.change_pct > 0 ? 'text-red-500' : r.change_pct < 0 ? 'text-green-500' : '') : ''}`}>
                                        {r.change_pct != null ? `${r.change_pct > 0 ? '+' : ''}${r.change_pct.toFixed(2)}%` : '-'}
                                    </td>
                                    <td className="px-3 py-2 text-right text-xs">{fmtMcap(r.market_cap)}</td>
                                    <td className={`px-3 py-2 text-center text-xs ${POSITION_COLORS[r.position_zone || ''] || ''}`}>
                                        {POSITION_LABELS[r.position_zone || ''] || '-'}
                                    </td>
                                    <td className={`px-3 py-2 text-center text-xs font-medium ${GS_COLORS[r.gs_status || ''] || ''}`}>
                                        {GS_LABELS[r.gs_status || ''] || '-'}
                                    </td>
                                    <td className="px-3 py-2 text-center text-xs">{ORBIT_LABELS[r.orbit_status || ''] || '-'}</td>
                                    <td className="px-3 py-2 text-center text-xs">{DECISION_LABELS[r.decision_status || ''] || '-'}</td>
                                    <td className="px-3 py-2 text-center text-xs">{BULL_LABELS[r.bull_status || ''] || '-'}</td>
                                    <td className={`px-3 py-2 text-center text-xs font-medium ${TREND_COLORS[r.trend_status || ''] || ''}`}>
                                        {TREND_LABELS[r.trend_status || ''] || '-'}
                                    </td>
                                    <td className="px-3 py-2 text-right font-mono text-xs">{r.radar_wave?.toFixed(2) ?? '-'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {totalPages > 1 && (
                <div className="flex items-center justify-center gap-3 mt-3">
                    <button
                        className="p-1.5 rounded-md border border-slate-200 dark:border-slate-700 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed"
                        disabled={page <= 1}
                        onClick={() => setPage(p => Math.max(1, p - 1))}>
                        <ChevronLeft className="w-4 h-4" />
                    </button>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                        {page} / {totalPages}
                    </span>
                    <button
                        className="p-1.5 rounded-md border border-slate-200 dark:border-slate-700 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed"
                        disabled={page >= totalPages}
                        onClick={() => setPage(p => Math.min(totalPages, p + 1))}>
                        <ChevronRight className="w-4 h-4" />
                    </button>
                </div>
            )}
        </div>
    )
}
