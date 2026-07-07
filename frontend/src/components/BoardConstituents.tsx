import { useEffect, useState, useCallback } from 'react'
import { ChevronDown, ChevronUp, Star } from 'lucide-react'
import { api } from '@/services/api'
import type { ConstituentStock } from '@/types'

interface BoardConstituentsProps {
    symbol: string
    onSymbolChange?: (symbol: string) => void
}

function isBoardSymbol(symbol: string): boolean {
    const s = (symbol || '').toUpperCase()
    return s.endsWith('.EM') || s.endsWith('.THS')
}

export default function BoardConstituents({ symbol, onSymbolChange }: BoardConstituentsProps) {
    const [expanded, setExpanded] = useState(false)
    const [stocks, setStocks] = useState<ConstituentStock[]>([])
    const [loading, setLoading] = useState(false)
    const [boardName, setBoardName] = useState('')
    const [watchlistSet, setWatchlistSet] = useState<Set<string>>(new Set())
    const [wlLoading, setWlLoading] = useState<Record<string, boolean>>({})

    useEffect(() => {
        if (!isBoardSymbol(symbol)) {
            setStocks([])
            setBoardName('')
            return
        }
        let cancelled = false
        const load = async () => {
            setLoading(true)
            try {
                const [resp, overview] = await Promise.all([
                    api.getBoardConstituents(symbol),
                    api.getPortfolioOverview().catch(() => null),
                ])
                if (cancelled) return
                setStocks(resp.stocks || [])
                setBoardName(resp.name || '')
                if (overview?.watchlist) {
                    const ws = new Set(overview.watchlist.map((w: any) => w.symbol))
                    setWatchlistSet(ws)
                }
            } catch { /* ignore */ }
            finally { if (!cancelled) setLoading(false) }
        }
        load()
        return () => { cancelled = true }
    }, [symbol])

    const toggleWatchlist = useCallback(async (stockSymbol: string) => {
        setWlLoading(prev => ({ ...prev, [stockSymbol]: true }))
        try {
            if (watchlistSet.has(stockSymbol)) {
                // Remove: need to find the watchlist item id
                const overview = await api.getPortfolioOverview()
                const item = overview.watchlist.find((w: any) => w.symbol.replace(/\.(SH|SZ|BJ)$/i, '') === stockSymbol.replace(/\.(SH|SZ|BJ)$/i, ''))
                if (item?.id) {
                    await api.removeFromWatchlist(item.id)
                    setWatchlistSet(prev => { const next = new Set(prev); next.delete(stockSymbol); return next })
                }
            } else {
                await api.addToWatchlist(stockSymbol)
                setWatchlistSet(prev => new Set(prev).add(stockSymbol))
            }
        } catch { /* ignore */ }
        finally { setWlLoading(prev => ({ ...prev, [stockSymbol]: false })) }
    }, [watchlistSet])

    const handleRowClick = (s: ConstituentStock, e: React.MouseEvent) => {
        if ((e.target as HTMLElement).closest('button')) return
        onSymbolChange?.(s.symbol)
    }

    if (!isBoardSymbol(symbol)) return null

    const formatPrice = (v?: number | null) => v != null ? v.toFixed(2) : '--'
    const formatPct = (v?: number | null) => {
        if (v == null) return '--'
        const s = v > 0 ? '+' : ''
        return `${s}${v.toFixed(2)}%`
    }

    return (
        <div className="card">
            <button
                onClick={() => setExpanded(!expanded)}
                className="flex items-center justify-between w-full text-sm font-medium text-slate-700 dark:text-slate-300"
            >
                <span>查看成分股{boardName ? `（${boardName}）` : ''}</span>
                <span className="flex items-center gap-1 text-slate-400">
                    {loading ? (
                        <span className="w-4 h-4 animate-spin rounded-full border-2 border-current border-r-transparent" />
                    ) : (
                        <span className="text-xs">{stocks.length}只</span>
                    )}
                    {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </span>
            </button>
            {expanded && (
                <div className="mt-2 max-h-[360px] overflow-y-auto rounded-md border border-slate-200 dark:border-slate-700">
                    <table className="w-full text-xs">
                        <thead className="sticky top-0 z-10 bg-slate-50 dark:bg-slate-800 text-slate-500">
                            <tr>
                                <th className="text-left px-2 py-1.5 font-medium">名称/代码</th>
                                <th className="text-right px-2 py-1.5 font-medium">最新价</th>
                                <th className="text-right px-2 py-1.5 font-medium">涨幅</th>
                                <th className="text-right px-2 py-1.5 font-medium">市值(亿)</th>
                                <th className="text-center px-1 py-1.5 font-medium w-10">自选</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
                            {stocks.map(s => {
                                const pctColor = (s.change_pct ?? 0) >= 0
                                    ? 'text-red-500' : 'text-emerald-500'
                                const inWl = watchlistSet.has(s.symbol)
                                const wlBusy = wlLoading[s.symbol]
                                return (
                                    <tr
                                        key={s.symbol}
                                        onClick={(e) => handleRowClick(s, e)}
                                        className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                                    >
                                        <td className="px-2 py-1.5">
                                            <span className="text-slate-900 dark:text-slate-200 font-medium">{s.name}</span>
                                            <span className="text-slate-400 ml-1.5">{s.symbol}</span>
                                        </td>
                                        <td className={`text-right px-2 py-1.5 font-mono ${pctColor}`}>
                                            {formatPrice(s.price)}
                                        </td>
                                        <td className={`text-right px-2 py-1.5 font-mono ${pctColor}`}>
                                            {formatPct(s.change_pct)}
                                        </td>
                                        <td className="text-right px-2 py-1.5 text-slate-500 font-mono">
                                            {s.market_cap != null ? s.market_cap.toFixed(1) : '--'}
                                        </td>
                                        <td className="text-center px-1 py-1.5">
                                            <button
                                                onClick={(e) => { e.stopPropagation(); toggleWatchlist(s.symbol) }}
                                                disabled={wlBusy}
                                                className="p-0.5"
                                            >
                                                {wlBusy ? (
                                                    <span className="w-3.5 h-3.5 animate-spin rounded-full border-2 border-amber-400 border-r-transparent inline-block" />
                                                ) : (
                                                    <Star className={`w-3.5 h-3.5 ${inWl ? 'fill-amber-400 text-amber-400' : 'text-slate-300 hover:text-amber-400'}`} />
                                                )}
                                            </button>
                                        </td>
                                    </tr>
                                )
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}
