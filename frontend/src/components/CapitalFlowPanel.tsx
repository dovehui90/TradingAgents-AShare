import { useEffect, useRef, useState } from 'react'
import {
    BusinessDay,
    ColorType,
    IChartApi,
    ISeriesApi,
    LineData,
    LineSeries,
    Time,
    createChart,
} from 'lightweight-charts'
import { TrendingUp } from 'lucide-react'
import { api } from '@/services/api'
import type { CapitalFlowLine, CapitalFlowSignal } from '@/types'

const LINE_COLORS: Record<string, string> = {
    '主力': '#ef4444',
    '游资': '#3b82f6',
    '大户': '#f59e0b',
    '散户': '#22c55e',
    '关注线': '#94a3b8',
}

const LINE_WIDTHS: Record<string, number> = {
    '主力': 2,
    '游资': 1.5,
    '大户': 1.5,
    '散户': 1.5,
    '关注线': 1,
}

export default function CapitalFlowPanel({ symbol }: { symbol: string }) {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const chartRef = useRef<IChartApi | null>(null)
    const seriesRefs = useRef<Record<string, ISeriesApi<'Line'>>>({})
    const [data, setData] = useState<CapitalFlowLine[]>([])
    const [signal, setSignal] = useState<CapitalFlowSignal | null>(null)
    const [stockName, setStockName] = useState('')
    const [isDark, setIsDark] = useState(document.documentElement.classList.contains('dark'))

    useEffect(() => {
        const observer = new MutationObserver(() => {
            setIsDark(document.documentElement.classList.contains('dark'))
        })
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
        return () => observer.disconnect()
    }, [])

    // Init chart
    useEffect(() => {
        if (!containerRef.current) return

        const textColor = isDark ? '#94a3b8' : '#475569'
        const gridColor = isDark ? 'rgba(51, 65, 85, 0.4)' : 'rgba(203, 213, 225, 0.4)'

        const chart = createChart(containerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: 'transparent' },
                textColor,
                attributionLogo: false,
            },
            localization: { locale: 'zh-CN', dateFormat: 'yyyy-MM-dd' },
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight,
            grid: { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
            rightPriceScale: {
                borderColor: isDark ? '#334155' : '#cbd5e1',
                scaleMargins: { top: 0.05, bottom: 0.05 },
            },
            timeScale: {
                borderColor: isDark ? '#334155' : '#cbd5e1',
                timeVisible: true,
                rightOffset: 6,
            },
            crosshair: {
                vertLine: { color: isDark ? 'rgba(59, 130, 246, 0.25)' : 'rgba(59, 130, 246, 0.15)' },
                horzLine: { color: isDark ? 'rgba(59, 130, 246, 0.25)' : 'rgba(59, 130, 246, 0.15)' },
            },
        })

        const names = ['主力', '游资', '大户', '散户', '关注线']
        const sr: Record<string, ISeriesApi<'Line'>> = {}
        for (const name of names) {
            sr[name] = chart.addSeries(LineSeries, {
                color: LINE_COLORS[name] || '#888',
                lineWidth: (LINE_WIDTHS[name] || 1) as 1 | 2,
                priceLineVisible: false,
                lastValueVisible: true,
            })
        }

        seriesRefs.current = sr
        chartRef.current = chart

        const onResize = () => {
            if (!containerRef.current || !chartRef.current) return
            chartRef.current.applyOptions({
                width: containerRef.current.clientWidth,
                height: containerRef.current.clientHeight,
            })
        }
        window.addEventListener('resize', onResize)

        return () => {
            window.removeEventListener('resize', onResize)
            chartRef.current?.remove()
            chartRef.current = null
            seriesRefs.current = {}
        }
    }, [isDark])

    // Load data
    useEffect(() => {
        let cancelled = false
        ;(async () => {
            try {
                const resp = await api.getCapitalFlow(symbol, 180)
                if (cancelled) return
                setData(resp.lines)
                setSignal(resp.signal)
                setStockName(resp.name || symbol)

                const sr = seriesRefs.current
                if (!sr['主力']) return

                // Build dataset per line from the first line's dates
                const refLine = resp.lines[0]
                if (!refLine) return

                for (const line of resp.lines) {
                    const series = sr[line.name]
                    if (!series) continue

                    const lineData: LineData[] = []
                    for (let i = 0; i < line.dates.length; i++) {
                        const v = line.history[i]
                        if (v == null) continue
                        const d = line.dates[i]
                        const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d)
                        if (!m) continue
                        const time: Time = {
                            year: Number(m[1]),
                            month: Number(m[2]),
                            day: Number(m[3]),
                        } as BusinessDay
                        lineData.push({ time, value: v })
                    }
                    series.setData(lineData)
                }
                chartRef.current?.timeScale().fitContent()
            } catch { /* noop */ }
        })()
        return () => { cancelled = true }
    }, [symbol])

    return (
        <div className="card">
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-red-500" />
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        资金流向 {stockName ? `· ${stockName}` : ''}
                    </span>
                </div>
                {signal && (
                    <div className="flex items-center gap-3 text-xs">
                        <span className={`px-2 py-0.5 rounded text-white font-bold ${
                            signal.strength >= 4 ? 'bg-red-500' :
                            signal.strength >= 3 ? 'bg-amber-500' :
                            signal.strength >= 2 ? 'bg-slate-400' : 'bg-slate-500'
                        }`}>
                            {signal.signal}
                        </span>
                    </div>
                )}
            </div>

            {/* Legend */}
            <div className="flex flex-wrap gap-3 mb-1 text-xs">
                {['主力', '游资', '大户', '散户', '关注线'].map(name => {
                    const line = data.find(l => l.name === name)
                    return (
                        <span key={name} className="flex items-center gap-1">
                            <span className="inline-block w-3 h-0.5" style={{ backgroundColor: LINE_COLORS[name] }} />
                            <span className="text-slate-500 dark:text-slate-400">{name}</span>
                            {line && (
                                <span className="font-medium text-slate-700 dark:text-slate-200">
                                    {line.latest.toFixed(2)}%
                                </span>
                            )}
                        </span>
                    )
                })}
            </div>

            {/* Chart */}
            <div className="relative h-[180px] rounded-md border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 overflow-hidden">
                <div ref={containerRef} className="absolute inset-0" />
            </div>

            {/* Signal details */}
            {signal && signal.details.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                    {signal.details.map((d, i) => (
                        <span key={i} className="text-xs px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                            {d}
                        </span>
                    ))}
                </div>
            )}
        </div>
    )
}
