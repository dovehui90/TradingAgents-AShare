import { useEffect, useMemo, useRef, useState } from 'react'
import {
    BusinessDay,
    ColorType,
    IChartApi,
    ISeriesApi,
    LineData,
    LineSeries,
    LineStyle,
    MouseEventParams,
    Time,
    UTCTimestamp,
    createChart,
    createSeriesMarkers,
} from 'lightweight-charts'
import { api } from '@/services/api'
import type { RadarPoint, KlinePeriod } from '@/types'
import { useAnalysisStore } from '@/stores/analysisStore'

interface ForceRadarPanelProps {
    symbol: string
    onChartReady?: (chart: IChartApi) => void
    onSyncNow?: () => void
}

function toChartTime(value: string, period: KlinePeriod): Time | null {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
    if (!m) return null
    const year = Number(m[1])
    const month = Number(m[2])
    const day = Number(m[3])
    if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null
    if (period === 'daily') {
        return { year, month, day } as BusinessDay
    }
    return (Date.UTC(year, month - 1, day) / 1000) as UTCTimestamp
}

export default function ForceRadarPanel({ symbol, onChartReady, onSyncNow }: ForceRadarPanelProps) {
    const klinePeriod = useAnalysisStore((state) => state.klinePeriod)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const chartRef = useRef<IChartApi | null>(null)
    const mainSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
    const retailSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
    const zeroLineRef = useRef<ISeriesApi<'Line'> | null>(null)
    const markersRef = useRef<any>(null)
    const cacheRef = useRef<RadarPoint[]>([])
    const cachePeriodRef = useRef<KlinePeriod>('daily')
    const [data, setData] = useState<RadarPoint[]>([])
    const [hoverData, setHoverData] = useState<{ main: number | null; retail: number | null } | null>(null)
    const [isDark, setIsDark] = useState(document.documentElement.classList.contains('dark'))

    const range = useMemo(() => {
        const end = new Date()
        const rangeDays = klinePeriod === 'daily' ? 365 : klinePeriod === 'weekly' ? 730 : 1825
        const start = new Date(end.getTime() - rangeDays * 24 * 60 * 60 * 1000)
        const toText = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
        return { start: toText(start), end: toText(end) }
    }, [klinePeriod])

    useEffect(() => {
        const observer = new MutationObserver(() => {
            setIsDark(document.documentElement.classList.contains('dark'))
        })
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
        return () => observer.disconnect()
    }, [])

    useEffect(() => {
        if (!containerRef.current) return

        const textColor = isDark ? '#94a3b8' : '#475569'
        const gridColor = isDark ? 'rgba(51, 65, 85, 0.6)' : 'rgba(203, 213, 225, 0.6)'

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
                tickMarkFormatter: (time: Time) => {
                    if (typeof time === 'number') {
                        const d = new Date(time * 1000)
                        return `${d.getUTCFullYear()}/${String(d.getUTCMonth() + 1).padStart(2, '0')}/${String(d.getUTCDate()).padStart(2, '0')}`
                    }
                    if (typeof time === 'object') {
                        return `${time.year}/${String(time.month).padStart(2, '0')}/${String(time.day).padStart(2, '0')}`
                    }
                    return String(time)
                },
            },
            crosshair: {
                vertLine: { color: isDark ? 'rgba(59, 130, 246, 0.35)' : 'rgba(59, 130, 246, 0.25)' },
                horzLine: { color: isDark ? 'rgba(59, 130, 246, 0.35)' : 'rgba(59, 130, 246, 0.25)' },
            },
        })

        // 主力线（蓝）= ths_zhuli
        const mainSeries = chart.addSeries(LineSeries, {
            color: '#3b82f6', lineWidth: 2, lineStyle: LineStyle.Solid,
            priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: true,
        })
        // 散户线（红）= ths_sanhu
        const retailSeries = chart.addSeries(LineSeries, {
            color: '#ef4444', lineWidth: 1, lineStyle: LineStyle.Solid,
            priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: true,
        })
        // 0轴线（灰色虚线）
        const zeroLine = chart.addSeries(LineSeries, {
            color: isDark ? '#64748b' : '#94a3b8', lineWidth: 1, lineStyle: LineStyle.Dashed,
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        })

        const markers = createSeriesMarkers(mainSeries)
        markersRef.current = markers

        if (cacheRef.current.length && cachePeriodRef.current === klinePeriod) {
            const mainData: LineData[] = []
            const retailData: LineData[] = []
            for (const p of cacheRef.current) {
                const t = toChartTime(p.date, klinePeriod)
                if (!t) continue
                if (p.ths_zhuli != null) mainData.push({ time: t, value: p.ths_zhuli })
                if (p.ths_sanhu != null) retailData.push({ time: t, value: p.ths_sanhu })
            }
            mainSeries.setData(mainData)
            retailSeries.setData(retailData)
            if (mainData.length > 0 && zeroLineRef.current) {
                zeroLineRef.current.setData([{ time: mainData[0].time, value: 0 }, { time: mainData[mainData.length - 1].time, value: 0 }])
            }
            const signalMarkers = cacheRef.current
                .filter(p => p.radar_buy || p.radar_sell || p.radar_top || p.radar_down)
                .map(p => {
                    const t = toChartTime(p.date, klinePeriod)
                    if (!t) return null
                    if (p.radar_buy) return { time: t, position: 'belowBar' as const, color: '#ef4444', shape: 'arrowUp' as const, text: '底' }
                    if (p.radar_sell) return { time: t, position: 'belowBar' as const, color: '#f59e0b', shape: 'arrowUp' as const, text: '升' }
                    if (p.radar_top) return { time: t, position: 'aboveBar' as const, color: '#22c55e', shape: 'arrowDown' as const, text: '顶' }
                    if (p.radar_down) return { time: t, position: 'aboveBar' as const, color: '#06b6d4', shape: 'arrowDown' as const, text: '下' }
                    return null
                })
                .filter(Boolean)
            markers.setMarkers(signalMarkers as any)
            chart.timeScale().fitContent()
        }

        mainSeriesRef.current = mainSeries
        retailSeriesRef.current = retailSeries
        zeroLineRef.current = zeroLine
        chartRef.current = chart
        onChartReady?.(chart)

        const handleCrosshairMove = (param: MouseEventParams) => {
            if (!param.time) { setHoverData(null); return }
            const mainVal = param.seriesData.get(mainSeries) as LineData | undefined
            const retailVal = param.seriesData.get(retailSeries) as LineData | undefined
            setHoverData({ main: mainVal?.value ?? null, retail: retailVal?.value ?? null })
        }
        chart.subscribeCrosshairMove(handleCrosshairMove)

        const onResize = () => {
            if (!containerRef.current || !chartRef.current) return
            chartRef.current.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight })
        }
        window.addEventListener('resize', onResize)

        return () => {
            window.removeEventListener('resize', onResize)
            chart.unsubscribeCrosshairMove(handleCrosshairMove)
            chartRef.current?.remove()
            chartRef.current = null
            mainSeriesRef.current = null
            retailSeriesRef.current = null
            zeroLineRef.current = null
        }
    }, [isDark, klinePeriod])

    useEffect(() => {
        let cancelled = false
        const ac = new AbortController()
        const load = async () => {
            if (!mainSeriesRef.current) return
            try {
                const resp = await api.getRadar(symbol, range.start, range.end, klinePeriod, ac.signal)
                if (cancelled || ac.signal.aborted || !resp?.points) return
                if (useAnalysisStore.getState().klinePeriod !== klinePeriod) return

                setData(resp.points)
                cacheRef.current = resp.points
                cachePeriodRef.current = klinePeriod

                const mainData: LineData[] = []
                const retailData: LineData[] = []
                for (const p of resp.points) {
                    const time = toChartTime(p.date, klinePeriod)
                    if (!time) continue
                    if (p.ths_zhuli != null) mainData.push({ time, value: p.ths_zhuli })
                    if (p.ths_sanhu != null) retailData.push({ time, value: p.ths_sanhu })
                }
                mainSeriesRef.current?.setData(mainData)
                retailSeriesRef.current?.setData(retailData)
                if (mainData.length > 0 && zeroLineRef.current) {
                    zeroLineRef.current.setData([{ time: mainData[0].time, value: 0 }, { time: mainData[mainData.length - 1].time, value: 0 }])
                }

                const signalMarkers = resp.points
                    .filter(p => p.radar_buy || p.radar_sell || p.radar_top || p.radar_down)
                    .map(p => {
                        const time = toChartTime(p.date, klinePeriod)
                        if (!time) return null
                        if (p.radar_buy) return { time, position: 'belowBar' as const, color: '#ef4444', shape: 'arrowUp' as const, text: '底' }
                        if (p.radar_sell) return { time, position: 'belowBar' as const, color: '#f59e0b', shape: 'arrowUp' as const, text: '升' }
                        if (p.radar_top) return { time, position: 'aboveBar' as const, color: '#22c55e', shape: 'arrowDown' as const, text: '顶' }
                        if (p.radar_down) return { time, position: 'aboveBar' as const, color: '#06b6d4', shape: 'arrowDown' as const, text: '下' }
                        return null
                    })
                    .filter(Boolean)
                markersRef.current?.setMarkers(signalMarkers as any)
                chartRef.current?.timeScale().fitContent()
                setTimeout(() => onSyncNow?.(), 100)
            } catch { if (ac.signal.aborted) return }
        }
        load()
        return () => { cancelled = true; ac.abort() }
    }, [symbol, range.start, range.end, klinePeriod, onSyncNow])

    const lastPoint = data.length ? data[data.length - 1] : null

    return (
        <div className="card">
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-300">自研主力雷达</span>
                </div>
                {lastPoint && (
                    <div className="flex items-center gap-3 text-xs">
                        <span className="flex items-center gap-1">
                            <span className="inline-block w-3 h-0.5 bg-blue-500" />
                            <span className="text-slate-500 dark:text-slate-400">主力</span>
                            <span className="text-blue-500 font-medium">{hoverData?.main?.toFixed(2) ?? lastPoint.ths_zhuli?.toFixed(2) ?? '--'}</span>
                        </span>
                        <span className="flex items-center gap-1">
                            <span className="inline-block w-3 h-0.5 bg-red-500" />
                            <span className="text-slate-500 dark:text-slate-400">散户</span>
                            <span className="text-red-500 font-medium">{hoverData?.retail?.toFixed(2) ?? lastPoint.ths_sanhu?.toFixed(2) ?? '--'}</span>
                        </span>
                        {lastPoint.radar_buy && <span className="text-red-500 font-bold">底</span>}
                        {lastPoint.radar_sell && <span className="text-amber-500 font-bold">升</span>}
                        {lastPoint.radar_top && <span className="text-green-500 font-bold">顶</span>}
                        {lastPoint.radar_down && <span className="text-cyan-500 font-bold">下</span>}
                    </div>
                )}
            </div>
            <div className="relative h-[150px] rounded-md border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 overflow-hidden">
                <div ref={containerRef} className="absolute inset-0" />
            </div>
        </div>
    )
}
