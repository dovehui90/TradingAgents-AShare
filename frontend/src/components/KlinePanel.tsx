import { useEffect, useMemo, useRef, useState } from 'react'
import {
    BusinessDay,
    CandlestickData,
    CandlestickSeries,
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
import { Activity, Bookmark, CandlestickChart, Search, Star, X } from 'lucide-react'
import { api } from '@/services/api'
import type { KlineCandle, NiuxiongPoint, GSPoint, SupportResistancePoint, TdPoint, IndicatorMode, KlinePeriod, WatchlistItem } from '@/types'
import { useAnalysisStore } from '@/stores/analysisStore'
import DarkPoolDrawer from './DarkPoolDrawer'

interface KlinePanelProps {
    symbol: string
    onSymbolChange?: (symbol: string) => void
    onChartReady?: (chart: IChartApi) => void
    onSyncNow?: () => void
}

function toDateText(date: Date): string {
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    return `${y}-${m}-${d}`
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

const SYMBOL_NAME_MAP: Record<string, string> = {
    '000001.SH': '上证指数',
    '399001.SZ': '深证成指',
    '399006.SZ': '创业板指',
    '000300.SH': '沪深300',
    '000905.SH': '中证500',
    '000852.SH': '中证1000',
    '300750.SZ': '宁德时代',
    '600406.SH': '国电南瑞',
    '510300.SH': '沪深300ETF',
}

function getDisplayName(symbol: string): string {
    const s = symbol.toUpperCase()
    return SYMBOL_NAME_MAP[s] ? `${SYMBOL_NAME_MAP[s]}（${s}）` : s
}

function formatNumber(value?: number | null, digits = 2): string {
    if (value == null || !Number.isFinite(value)) return '--'
    return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    }).format(value)
}

function formatVolume(value?: number | null): string {
    if (value == null || !Number.isFinite(value)) return '--'
    if (Math.abs(value) >= 1e8) return `${formatNumber(value / 1e8, 2)}亿`
    if (Math.abs(value) >= 1e4) return `${formatNumber(value / 1e4, 2)}万`
    return formatNumber(value, 0)
}

const INDEX_PRESETS = [
    { symbol: '000001.SH', label: '上证指数' },
    { symbol: '399001.SZ', label: '深证成指' },
    { symbol: '399006.SZ', label: '创业板指' },
    { symbol: '000688.SH', label: '科创50' },
] as const

export default function KlinePanel({ symbol, onSymbolChange, onChartReady, onSyncNow }: KlinePanelProps) {
    const currentAnalysisSymbol = useAnalysisStore((state) => state.currentSymbol)
    const klinePeriod = useAnalysisStore((state) => state.klinePeriod)
    const setKlinePeriod = useAnalysisStore((state) => state.setKlinePeriod)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const srMarkerContainerRef = useRef<HTMLDivElement | null>(null)
    const chartRef = useRef<IChartApi | null>(null)
    const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
    const markersRef = useRef<any>(null)
    const niuxiongSeriesRefs = useRef<Record<string, ISeriesApi<'Line'>>>({})
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [isDark, setIsDark] = useState(document.documentElement.classList.contains('dark'))
    const [candles, setCandles] = useState<KlineCandle[]>([])
    const [activeCandle, setActiveCandle] = useState<KlineCandle | null>(null)
    const [niuxiongData, setNiuxiongData] = useState<NiuxiongPoint[]>([])
    const [indicatorMode, setIndicatorMode] = useState<IndicatorMode>('combined')
    const indicatorModeRef = useRef<IndicatorMode>('combined')
    const gsSeriesRefs = useRef<Record<string, ISeriesApi<'Line'>>>({})
    const [gsData, setGsData] = useState<GSPoint[]>([])
    const showGsLinesRef = useRef(false)
    const [srData, setSrData] = useState<SupportResistancePoint[]>([])
    const [tdData, setTdData] = useState<TdPoint[]>([])
    const tdMarkerContainerRef = useRef<HTMLDivElement | null>(null)
    const [showSr, setShowSr] = useState(false)
    const showSrRef = useRef(false)
    const [showTd, setShowTd] = useState(false)
    const showTdRef = useRef(false)
    const srSeriesRefs = useRef<Record<string, ISeriesApi<'Line'>>>({})
    const candlesRef = useRef<KlineCandle[]>([])
    const candlesPeriodRef = useRef<KlinePeriod>('daily')
    const [stockName, setStockName] = useState<string | null>(null)
    const [darkPoolOpen, setDarkPoolOpen] = useState(false)
    const [darkPoolPreloaded, setDarkPoolPreloaded] = useState(false)
    const [watchlistItemId, setWatchlistItemId] = useState<string | null>(null)
    const [watchlistLoading, setWatchlistLoading] = useState(false)
    const [favorites, setFavorites] = useState<Array<{ symbol: string; name: string }>>(() => {
        try {
            const saved = localStorage.getItem('kline_favorites')
            return saved ? JSON.parse(saved) : []
        } catch { return [] }
    })

    const persistFavorites = (items: Array<{ symbol: string; name: string }>) => {
        setFavorites(items)
        try { localStorage.setItem('kline_favorites', JSON.stringify(items)) } catch { /* noop */ }
    }

    const isFavorited = favorites.some(f => f.symbol === symbol)

    const toggleFavorite = () => {
        if (isFavorited) {
            persistFavorites(favorites.filter(f => f.symbol !== symbol))
        } else {
            const name = stockName || getDisplayName(symbol)
            persistFavorites([...favorites, { symbol, name }])
        }
    }

    // 自选状态：symbol 变化时查询是否已在自选中
    useEffect(() => {
        let cancelled = false
        const check = async () => {
            try {
                const overview = await api.getPortfolioOverview()
                if (cancelled) return
                const item = overview.watchlist.find(
                    (w: WatchlistItem) => w.symbol.replace(/\.(SH|SZ|BJ)$/i, '') === symbol.replace(/\.(SH|SZ|BJ)$/i, ''),
                )
                setWatchlistItemId(item?.id ?? null)
            } catch { /* 静默 */ }
        }
        check()
        return () => { cancelled = true }
    }, [symbol])

    const handleToggleWatchlist = async () => {
        setWatchlistLoading(true)
        try {
            if (watchlistItemId) {
                await api.removeFromWatchlist(watchlistItemId)
                setWatchlistItemId(null)
            } else {
                const res = await api.addToWatchlist(symbol)
                const added = res.results.find(r => r.status === 'added')
                if (added?.item) setWatchlistItemId(added.item.id)
            }
        } catch { /* 静默 */ }
        finally { setWatchlistLoading(false) }
    }

    // 预加载：symbol变化时后台拉取分析数据
    useEffect(() => {
        if (!symbol || symbol.startsWith('0.') || symbol.startsWith('9.')) return
        setDarkPoolPreloaded(false)
        let cancelled = false
        const preload = async () => {
            try {
                await api.getDarkPoolAnalysis(symbol)
                if (!cancelled) setDarkPoolPreloaded(true)
            } catch { /* 静默失败 */ }
        }
        preload()
        return () => { cancelled = true }
    }, [symbol])

    const range = useMemo(() => {
        const end = new Date()
        const rangeDays = klinePeriod === 'daily' ? 365 : klinePeriod === 'weekly' ? 730 : 1825
        const start = new Date(end.getTime() - rangeDays * 24 * 60 * 60 * 1000)
        return {
            start: toDateText(start),
            end: toDateText(end),
        }
    }, [klinePeriod])

    const updateNiuxiongSeries = (points: NiuxiongPoint[]) => {
        const seriesMap = niuxiongSeriesRefs.current
        if (!seriesMap.decision_line) return
        const mode = indicatorModeRef.current
        const showNx = mode === 'niuxiong' || mode === 'combined'

        // decision_line, bull_line, bear_line: 直接映射
        const simpleKeys = ['decision_line', 'bull_line', 'bear_line'] as const
        for (const key of simpleKeys) {
            const lineData: LineData[] = []
            if (showNx) {
                for (const p of points) {
                    const val = p[key]
                    if (val == null) continue
                    const time = toChartTime(p.date, klinePeriod)
                    if (!time) continue
                    lineData.push({ time, value: val })
                }
            }
            seriesMap[key]?.setData(lineData)
        }

        // orbit_line: 单一青色实线
        const orbitData: LineData[] = []
        if (showNx) {
            for (const p of points) {
                if (p.orbit_line == null) continue
                const time = toChartTime(p.date, klinePeriod)
                if (!time) continue
                orbitData.push({ time, value: p.orbit_line })
            }
        }
        seriesMap.orbit_line?.setData(orbitData)

        chartRef.current?.timeScale().fitContent()
    }

    const updateGsSeries = (points: GSPoint[]) => {
        const seriesMap = gsSeriesRefs.current
        if (!seriesMap.gs_bb) return

        const mode = indicatorModeRef.current
        const showGs = mode === 'niuxiong' || mode === 'combined'
        const showLines = showGs && showGsLinesRef.current

        // BB line
        const bbData: LineData[] = []
        if (showLines) {
            for (const p of points) {
                if (p.bb_line == null) continue
                const time = toChartTime(p.date, klinePeriod)
                if (!time) continue
                bbData.push({ time, value: p.bb_line })
            }
        }
        seriesMap.gs_bb.setData(bbData)

        // A line
        const aData: LineData[] = []
        if (showLines) {
            for (const p of points) {
                if (p.a_line == null) continue
                const time = toChartTime(p.date, klinePeriod)
                if (!time) continue
                aData.push({ time, value: p.a_line })
            }
        }
        seriesMap.gs_a.setData(aData)

        // GS buy/sell markers
        if (markersRef.current && showGs) {
            const markers = points
                .filter(p => p.buy_signal || p.sell_signal)
                .map(p => {
                    const time = toChartTime(p.date, klinePeriod)
                    if (!time) return null
                    return {
                        time,
                        position: p.buy_signal ? ('belowBar' as const) : ('aboveBar' as const),
                        color: p.buy_signal ? '#ef4444' : '#22c55e',
                        shape: p.buy_signal ? ('arrowUp' as const) : ('arrowDown' as const),
                        text: p.buy_signal ? 'G' : 'S',
                    }
                })
                .filter(Boolean)
            markersRef.current.setMarkers(markers as any)
        } else if (markersRef.current) {
            markersRef.current.setMarkers([])
        }

        chartRef.current?.timeScale().fitContent()
    }

    const renderTdMarkers = (points: TdPoint[]) => {
        const container = tdMarkerContainerRef.current
        const chart = chartRef.current
        if (!container || !chart) { if (container) container.innerHTML = ''; return }
        container.innerHTML = ''
        const chartWidth = container.clientWidth
        for (const p of points) {
            if (p.buy_count === 0 && p.sell_count === 0) continue
            const time = toChartTime(p.date, klinePeriod)
            if (!time) continue
            const x = chart.timeScale().timeToCoordinate(time)
            if (x == null || x < -20 || x > chartWidth + 20) continue
            // Get y position from candlestick series
            const candleSeries = seriesRef.current
            if (!candleSeries) continue
            const yHigh = candleSeries.priceToCoordinate(p.close * 1.02)
            const yLow = candleSeries.priceToCoordinate(p.close * 0.98)
            if (yHigh == null || yLow == null) continue
            if (p.sell_count > 0) {
                const div = document.createElement('div')
                div.textContent = String(p.sell_count)
                div.style.cssText = `position:absolute;left:${x - 5}px;top:${yHigh - 14}px;font-size:${p.sell_count === 9 ? '9px' : '8px'};color:${p.sell_count === 9 ? '#fff' : '#ef4444'};background:${p.sell_count === 9 ? '#ef4444' : 'transparent'};border-radius:50%;width:${p.sell_count === 9 ? '14px' : '11px'};height:${p.sell_count === 9 ? '14px' : '11px'};display:flex;align-items:center;justify-content:center;pointer-events:none;`
                container.appendChild(div)
            }
            if (p.buy_count > 0) {
                const div = document.createElement('div')
                div.textContent = String(p.buy_count)
                div.style.cssText = `position:absolute;left:${x - 5}px;top:${yLow + 2}px;font-size:${p.buy_count === 9 ? '9px' : '8px'};color:${p.buy_count === 9 ? '#fff' : '#22c55e'};background:${p.buy_count === 9 ? '#22c55e' : 'transparent'};border-radius:50%;width:${p.buy_count === 9 ? '14px' : '11px'};height:${p.buy_count === 9 ? '14px' : '11px'};display:flex;align-items:center;justify-content:center;pointer-events:none;`
                container.appendChild(div)
            }
        }
    }

    const updateSrSeries = (points: SupportResistancePoint[]) => {
        const srMap = srSeriesRefs.current
        if (!srMap.sr_support) return
        const show = showSrRef.current
        const chart = chartRef.current

        // Remove old segment series
        for (const key of Object.keys(srMap)) {
            if (key.startsWith('sr_seg_')) {
                srMap[key].setData([])
            }
        }

        if (!show || !chart) {
            srMap.sr_support.setData([])
            srMap.sr_resistance.setData([])
            srMarkerContainerRef.current && (srMarkerContainerRef.current.innerHTML = '')
            chart?.timeScale().fitContent()
            return
        }

        // Build segments for a field (support or resistance)
        const buildSegments = (getter: (p: SupportResistancePoint) => number | null | undefined, color: string) => {
            let segStart: { time: Time; value: number } | null = null
            let prevVal: number | null = null
            const segments: { start: { time: Time; value: number }; end: { time: Time; value: number } }[] = []

            for (const p of points) {
                const val = getter(p)
                if (val == null) continue
                const time = toChartTime(p.date, klinePeriod)
                if (!time) continue

                if (segStart === null) {
                    segStart = { time, value: val }
                } else if (val !== prevVal) {
                    // Value changed — close previous segment, start new one
                    segments.push({ start: segStart, end: { time, value: prevVal! } })
                    segStart = { time, value: val }
                }
                prevVal = val
            }
            // Close last segment
            if (segStart && prevVal !== null) {
                const lastPt = points.filter(p => getter(p) != null).slice(-1)[0]
                if (lastPt) {
                    const lastTime = toChartTime(lastPt.date, klinePeriod)
                    if (lastTime) segments.push({ start: segStart, end: { time: lastTime, value: prevVal } })
                }
            }

            // Create line series for each segment + marker at start
            segments.forEach((seg, i) => {
                const key = `sr_seg_${color}_${i}`
                if (!srMap[key]) {
                    srMap[key] = chart.addSeries(LineSeries, {
                        color,
                        lineWidth: 1,
                        lineStyle: LineStyle.Solid,
                        priceLineVisible: false,
                        lastValueVisible: false,
                        crosshairMarkerVisible: false,
                    })
                }
                srMap[key].setData([seg.start, seg.end])
                // Collect marker position for HTML triangle overlay
                srMarkerList.push({ time: seg.start.time, value: seg.start.value, isSupport: color === '#ef4444' })
            })
        }

        // Use main series for the most recent segment (shows last value in price scale)
        const lastSupport = points.filter(p => p.support != null).slice(-1)[0]
        const lastResistance = points.filter(p => p.resistance != null).slice(-1)[0]
        if (lastSupport) {
            const t = toChartTime(lastSupport.date, klinePeriod)
            if (t) srMap.sr_support.setData([{ time: t, value: lastSupport.support! }])
        }
        if (lastResistance) {
            const t = toChartTime(lastResistance.date, klinePeriod)
            if (t) srMap.sr_resistance.setData([{ time: t, value: lastResistance.resistance! }])
        }

        const srMarkerList: { time: Time; value: number; isSupport: boolean }[] = []
        buildSegments(p => p.support, '#ef4444')
        buildSegments(p => p.resistance, '#22c55e')

        // Render HTML triangle markers
        const renderSrMarkers = () => {
            const container = srMarkerContainerRef.current
            if (!container || !chart) { if (container) container.innerHTML = ''; return }
            container.innerHTML = ''
            for (const m of srMarkerList) {
                const x = chart.timeScale().timeToCoordinate(m.time)
                const series = m.isSupport ? srMap.sr_support : srMap.sr_resistance
                const y = series?.priceToCoordinate(m.value)
                if (x == null || y == null) continue
                const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
                svg.setAttribute('width', '10')
                svg.setAttribute('height', '8')
                svg.setAttribute('viewBox', '0 0 10 8')
                svg.style.position = 'absolute'
                svg.style.left = `${x - 5}px`
                svg.style.top = m.isSupport ? `${y + 2}px` : `${y - 10}px`
                svg.style.pointerEvents = 'none'
                const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon')
                if (m.isSupport) {
                    poly.setAttribute('points', '0,8 5,0 10,8')
                    poly.setAttribute('fill', '#ef4444')
                } else {
                    poly.setAttribute('points', '0,0 5,8 10,0')
                    poly.setAttribute('fill', '#22c55e')
                }
                svg.appendChild(poly)
                container.appendChild(svg)
            }
        }
        renderSrMarkers()
        chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
            renderSrMarkers()
            if (showTdRef.current && tdData.length) renderTdMarkers(tdData)
        })
    }

    // Listen for theme changes
    useEffect(() => {
        const observer = new MutationObserver(() => {
            const dark = document.documentElement.classList.contains('dark')
            setIsDark(dark)
        })
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
        return () => observer.disconnect()
    }, [])

    useEffect(() => {
        if (!containerRef.current) return

        const textColor = isDark ? '#94a3b8' : '#475569'
        const gridColor = isDark ? 'rgba(51, 65, 85, 0.6)' : 'rgba(203, 213, 225, 0.6)'
        const bgColor = isDark ? 'transparent' : 'transparent'

        const chart = createChart(containerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: bgColor },
                textColor: textColor,
                attributionLogo: false,
            },
            localization: {
                locale: 'zh-CN',
                dateFormat: 'yyyy-MM-dd',
            },
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight,
            grid: {
                vertLines: { color: gridColor },
                horzLines: { color: gridColor },
            },
            rightPriceScale: {
                borderColor: isDark ? '#334155' : '#cbd5e1',
            },
            timeScale: {
                borderColor: isDark ? '#334155' : '#cbd5e1',
                timeVisible: true,
                rightOffset: 6,
                tickMarkFormatter: (time: Time) => {
                    if (typeof time === 'number') {
                        const d = new Date(time * 1000)
                        const y = d.getUTCFullYear()
                        const m = String(d.getUTCMonth() + 1).padStart(2, '0')
                        const day = String(d.getUTCDate()).padStart(2, '0')
                        return `${y}/${m}/${day}`
                    }
                    if (typeof time === 'object') {
                        const y = String(time.year)
                        const m = String(time.month).padStart(2, '0')
                        const d = String(time.day).padStart(2, '0')
                        return `${y}/${m}/${d}`
                    }
                    return String(time)
                },
            },
            crosshair: {
                vertLine: { color: isDark ? 'rgba(59, 130, 246, 0.35)' : 'rgba(59, 130, 246, 0.25)' },
                horzLine: { color: isDark ? 'rgba(59, 130, 246, 0.35)' : 'rgba(59, 130, 246, 0.25)' },
            },
        })

        const series = chart.addSeries(CandlestickSeries, {
            upColor: '#ef4444',
            downColor: '#22c55e',
            wickUpColor: '#ef4444',
            wickDownColor: '#22c55e',
            borderVisible: false,
        })

        // Niuxiong indicator line series
        const niuxiongColors: Record<string, { color: string; lineWidth: 1 | 2; lineStyle: LineStyle; title: string }> = {
            decision_line: { color: '#eab308', lineWidth: 1, lineStyle: LineStyle.Dashed, title: '决策线' },
            bull_line: { color: '#ef4444', lineWidth: 1, lineStyle: LineStyle.Dashed, title: '牛线' },
            bear_line: { color: '#22c55e', lineWidth: 1, lineStyle: LineStyle.Dashed, title: '熊线' },
            orbit_line: { color: '#b91c1c', lineWidth: 1, lineStyle: LineStyle.Solid, title: '轨道线' },
        }
        const seriesMap: Record<string, ISeriesApi<'Line'>> = {}
        for (const [key, cfg] of Object.entries(niuxiongColors)) {
            const s = chart.addSeries(LineSeries, {
                color: cfg.color,
                lineWidth: cfg.lineWidth,
                lineStyle: cfg.lineStyle,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
            })
            seriesMap[key] = s
        }
        niuxiongSeriesRefs.current = seriesMap

        // GS indicator line series
        const gsMap: Record<string, ISeriesApi<'Line'>> = {}
        gsMap.gs_bb = chart.addSeries(LineSeries, {
            color: '#e2e8f0',
            lineWidth: 1,
            lineStyle: LineStyle.Solid,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
        })
        gsMap.gs_a = chart.addSeries(LineSeries, {
            color: '#f59e0b',
            lineWidth: 2,
            lineStyle: LineStyle.Solid,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
        })
        gsSeriesRefs.current = gsMap

        // Support/Resistance indicator line series
        const srMap: Record<string, ISeriesApi<'Line'>> = {}
        srMap.sr_support = chart.addSeries(LineSeries, {
            color: '#ef4444', lineWidth: 1, lineStyle: LineStyle.Solid,
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        })
        srMap.sr_resistance = chart.addSeries(LineSeries, {
            color: '#22c55e', lineWidth: 1, lineStyle: LineStyle.Solid,
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        })
        srSeriesRefs.current = srMap

        chartRef.current = chart
        seriesRef.current = series
        markersRef.current = createSeriesMarkers(series)
        onChartReady?.(chart)

        if (candlesRef.current.length && candlesPeriodRef.current === klinePeriod) {
            const existingData: CandlestickData[] = candlesRef.current.flatMap((c) => {
                const time = toChartTime((c.date || '').slice(0, 10), klinePeriod)
                const open = Number(c.open)
                const high = Number(c.high)
                const low = Number(c.low)
                const close = Number(c.close)
                if (!time) return []
                if (![open, high, low, close].every(Number.isFinite)) return []
                return [{ time, open, high, low, close }]
            })
            series.setData(existingData)
            chart.timeScale().fitContent()
        }

        const handleCrosshairMove = (param: MouseEventParams) => {
            if (!param.time || !seriesRef.current) {
                setActiveCandle(candlesRef.current.length ? candlesRef.current[candlesRef.current.length - 1] : null)
                return
            }
            const pointData = param.seriesData.get(seriesRef.current) as CandlestickData | undefined
            if (!pointData) return
            let time: string
            if (typeof pointData.time === 'number') {
                const d = new Date(pointData.time * 1000)
                time = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`
            } else if (typeof pointData.time === 'object') {
                time = `${pointData.time.year}-${String(pointData.time.month).padStart(2, '0')}-${String(pointData.time.day).padStart(2, '0')}`
            } else {
                time = String(pointData.time)
            }
            const matched = candlesRef.current.find(c => c.date === time)
            if (matched) setActiveCandle(matched)
        }
        chart.subscribeCrosshairMove(handleCrosshairMove)

        const handleDblClick = () => {
            chartRef.current?.timeScale().fitContent()
        }
        containerRef.current.addEventListener('dblclick', handleDblClick)

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
            containerRef.current?.removeEventListener('dblclick', handleDblClick)
            chart.unsubscribeCrosshairMove(handleCrosshairMove)
            chartRef.current?.remove()
            chartRef.current = null
            seriesRef.current = null
            // Cleanup sub-chart
        }
    }, [isDark, klinePeriod])

    useEffect(() => {
        let cancelled = false
        const ac = new AbortController()

        const load = async () => {
            if (!seriesRef.current) return
            setLoading(true)
            setError(null)
            try {
                const [klineResp, niuxiongResp, gsResp, srResp, tdResp] = await Promise.all([
                    api.getKline(symbol, range.start, range.end, klinePeriod, ac.signal),
                    api.getNiuxiong(symbol, range.start, range.end, klinePeriod, ac.signal).catch(() => null),
                    api.getGsStrategy(symbol, range.start, range.end, klinePeriod, ac.signal).catch(() => null),
                    api.getSupportResistance(symbol, range.start, range.end, klinePeriod, ac.signal).catch(() => null),
                    api.getTdSequential(symbol, range.start, range.end, klinePeriod, ac.signal).catch(() => null),
                ])
                const data: CandlestickData[] = klineResp.candles.flatMap((c: KlineCandle) => {
                    const time = toChartTime((c.date || '').slice(0, 10), klinePeriod)
                    const open = Number(c.open)
                    const high = Number(c.high)
                    const low = Number(c.low)
                    const close = Number(c.close)
                    if (!time) return []
                    if (![open, high, low, close].every(Number.isFinite)) return []
                    if (open === 0 && high === 0 && low === 0) return []
                    return [{ time, open, high, low, close }]
                })

                if (cancelled || ac.signal.aborted) return
                if (useAnalysisStore.getState().klinePeriod !== klinePeriod) return
                const validCandles = klineResp.candles.filter((c: KlineCandle) => {
                    const o = Number(c.open), h = Number(c.high), l = Number(c.low)
                    return !(o === 0 && h === 0 && l === 0)
                })
                setCandles(validCandles)
                setStockName(klineResp.name || null)
                candlesRef.current = validCandles
                candlesPeriodRef.current = klinePeriod
                setActiveCandle(validCandles.length ? validCandles[validCandles.length - 1] : null)
                seriesRef.current?.setData(data)

                // Update niuxiong overlay
                if (niuxiongResp?.points) {
                    setNiuxiongData(niuxiongResp.points)
                    updateNiuxiongSeries(niuxiongResp.points)
                }

                // Update GS overlay
                if (gsResp?.points) {
                    setGsData(gsResp.points)
                    updateGsSeries(gsResp.points)
                }

                // Update Support/Resistance overlay
                if (srResp?.points) {
                    setSrData(srResp.points)
                    if (showSrRef.current) updateSrSeries(srResp.points)
                }

                // Update TD Sequential overlay
                if (tdResp?.points) {
                    setTdData(tdResp.points)
                }

                chartRef.current?.timeScale().fitContent()
                // 等待图表完成渲染后再画标记，避免坐标偏移
                requestAnimationFrame(() => {
                    if (showSrRef.current && srResp?.points) {
                        updateSrSeries(srResp.points)
                    }
                    if (showTdRef.current && tdResp?.points) {
                        renderTdMarkers(tdResp.points)
                    }
                })
                // K线数据加载完后触发同步到雷达
                setTimeout(() => onSyncNow?.(), 200)
                if (!data.length) {
                    setError('暂无可用K线数据')
                }
            } catch (e) {
                if (cancelled || ac.signal.aborted) return
                setError(e instanceof Error ? e.message : '加载K线失败')
                setCandles([])
                candlesRef.current = []
                setActiveCandle(null)
                seriesRef.current?.setData([])
            } finally {
                if (!cancelled && !ac.signal.aborted) setLoading(false)
            }
        }

        load()
        return () => {
            cancelled = true
            ac.abort()
        }
    }, [range.end, range.start, symbol, klinePeriod, onSyncNow])

    const panelCandle = activeCandle ?? (candles.length ? candles[candles.length - 1] : null)
    const panelChange = panelCandle?.change ?? (panelCandle ? panelCandle.close - panelCandle.open : null)
    const panelChangePercent = panelCandle?.change_percent ?? (
        panelCandle && panelCandle.open !== 0 ? (panelChange! / panelCandle.open) * 100 : null
    )
    const isUp = (panelChange ?? 0) >= 0
    const compactChangePercent = panelChangePercent == null ? '--' : `${panelChangePercent >= 0 ? '+' : ''}${formatNumber(panelChangePercent)}%`
    const showCurrentSymbolButton = !!currentAnalysisSymbol && currentAnalysisSymbol !== symbol
    const currentSymbolLabel = currentAnalysisSymbol ? getDisplayName(currentAnalysisSymbol).replace(/（.*?）/, '') : '当前标的'

    return (
        <>
        <section className="card h-full flex flex-col overflow-hidden">
            <div className="flex items-center justify-between mb-3 shrink-0">
                <div className="min-w-0 flex items-center gap-3">
                    <CandlestickChart className="w-5 h-5 text-cyan-500 max-sm:hidden" />
                    <div className="min-w-0 flex flex-wrap items-center gap-x-4 gap-y-1">
                        <h2 className="truncate text-lg font-semibold text-slate-900 dark:text-slate-100 max-sm:text-sm">{stockName ? `${stockName}（${symbol}）` : getDisplayName(symbol)} K线</h2>
                        <button
                            onClick={handleToggleWatchlist}
                            disabled={watchlistLoading}
                            className={`p-1 rounded-md transition-colors ${
                                watchlistItemId
                                    ? 'text-amber-500 bg-amber-100 dark:bg-amber-500/15 hover:text-amber-600'
                                    : 'text-slate-400 hover:text-amber-500 hover:bg-amber-100 dark:hover:bg-amber-500/15'
                            }`}
                            title={watchlistItemId ? '移出自选' : '加入自选'}
                        >
                            {watchlistLoading ? (
                                <div className="w-4 h-4 animate-spin rounded-full border-2 border-current border-r-transparent" />
                            ) : (
                                <Star className={`w-4 h-4 ${watchlistItemId ? 'fill-current' : ''}`} />
                            )}
                        </button>
                        <button
                            onClick={toggleFavorite}
                            className={`p-1 rounded-md transition-colors ${
                                isFavorited
                                    ? 'text-blue-500 bg-blue-100 dark:bg-blue-500/15 hover:text-blue-600'
                                    : 'text-slate-400 hover:text-blue-500 hover:bg-blue-100 dark:hover:bg-blue-500/15'
                            }`}
                            title={isFavorited ? '取消收藏' : '收藏当前视图'}
                        >
                            <Bookmark className={`w-4 h-4 ${isFavorited ? 'fill-current' : ''}`} />
                        </button>
                        <button
                            onClick={() => setDarkPoolOpen(true)}
                            className={`p-1 rounded-md transition-colors ${
                                darkPoolPreloaded
                                    ? 'text-purple-500 dark:text-purple-400 bg-purple-100 dark:bg-purple-500/15'
                                    : 'text-slate-400 hover:text-purple-500 dark:hover:text-purple-400 hover:bg-purple-100 dark:hover:bg-purple-500/15'
                            }`}
                            title={darkPoolPreloaded ? '盘面分析（已就绪）' : '盘面分析（加载中...）'}
                        >
                            <Search className="w-4 h-4" />
                        </button>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs max-sm:text-[11px] max-sm:gap-x-1.5">
                            <span className="text-slate-500 dark:text-slate-400">{panelCandle?.date || '--'}</span>
                            <span className={`font-medium ${isUp ? 'text-red-500' : 'text-emerald-500'}`}>收盘 {formatNumber(panelCandle?.close)}</span>
                            <span className="text-slate-500 dark:text-slate-400 max-sm:hidden">开盘 {formatNumber(panelCandle?.open)}</span>
                            <span className={`font-medium ${isUp ? 'text-red-500' : 'text-emerald-500'}`}>{compactChangePercent}</span>
                            <span className="text-slate-500 dark:text-slate-400 max-sm:hidden">高/低 {formatNumber(panelCandle?.high)} / {formatNumber(panelCandle?.low)}</span>
                            <span className="text-slate-500 dark:text-slate-400 max-sm:hidden">量 {formatVolume(panelCandle?.volume)}</span>
                            <span className="text-slate-500 dark:text-slate-400 max-sm:hidden">换手 {panelCandle?.turnover_rate == null ? '--' : `${formatNumber(panelCandle.turnover_rate)}%`}</span>
                            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600 max-sm:hidden" />
                            {([
                                { value: 'daily' as KlinePeriod, label: '日K' },
                                { value: 'weekly' as KlinePeriod, label: '周K' },
                                { value: 'monthly' as KlinePeriod, label: '月K' },
                            ]).map((item) => (
                                <button
                                    key={item.value}
                                    onClick={() => setKlinePeriod(item.value)}
                                    className={`text-xs px-1.5 py-0.5 rounded border transition-colors ${
                                        klinePeriod === item.value
                                            ? 'border-purple-500 text-purple-500 bg-purple-50 dark:bg-purple-500/10'
                                            : 'text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300'
                                    }`}
                                >
                                    {item.label}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-1.5 max-sm:hidden">
                    {showCurrentSymbolButton && (
                        <button
                            onClick={() => onSymbolChange?.(currentAnalysisSymbol)}
                            className="text-xs px-2.5 py-1 rounded border border-emerald-500 text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 hover:bg-emerald-100 dark:hover:bg-emerald-500/20 transition-colors"
                        >
                            {currentSymbolLabel}
                        </button>
                    )}
                    {INDEX_PRESETS.map((item) => (
                        <button
                            key={item.symbol}
                            onClick={() => onSymbolChange?.(item.symbol)}
                            className={`text-xs px-2 py-1 rounded border transition-colors ${item.symbol === symbol
                                    ? 'border-blue-500 text-blue-500 bg-blue-50 dark:bg-blue-500/10'
                                    : 'border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:border-slate-400 dark:hover:border-slate-500'
                                }`}
                        >
                            {item.label}
                        </button>
                    ))}
                    {favorites.map((fav) => (
                        <div key={fav.symbol} className="flex items-center gap-0.5">
                            <button
                                onClick={() => onSymbolChange?.(fav.symbol)}
                                className={`text-xs px-2 py-1 rounded-l border transition-colors truncate max-w-[120px] ${fav.symbol === symbol
                                        ? 'border-blue-500 text-blue-500 bg-blue-50 dark:bg-blue-500/10'
                                        : 'border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:border-slate-400 dark:hover:border-slate-500'
                                    }`}
                                title={fav.name}
                            >
                                {fav.name}
                            </button>
                            <button
                                onClick={(e) => { e.stopPropagation(); persistFavorites(favorites.filter(f => f.symbol !== fav.symbol)) }}
                                className="text-xs px-1 py-1 rounded-r border border-l-0 border-slate-200 dark:border-slate-600 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10"
                                title="移除收藏"
                            >
                                <X className="w-3 h-3" />
                            </button>
                        </div>
                    ))}
                    <button
                        onClick={() => {
                            const next = indicatorMode === 'off' ? 'combined' : 'off'
                            setIndicatorMode(next)
                            indicatorModeRef.current = next
                            const show = next === 'combined'
                            if (show) {
                                updateNiuxiongSeries(niuxiongData)
                                if (gsData.length) updateGsSeries(gsData)
                            } else {
                                for (const s of Object.values(niuxiongSeriesRefs.current)) s.setData([])
                                for (const s of Object.values(gsSeriesRefs.current)) s.setData([])
                                markersRef.current?.setMarkers([])
                            }
                        }}
                        className={`text-xs px-2 py-1 rounded border transition-colors ${indicatorMode !== 'off'
                            ? 'border-cyan-500 text-cyan-500 bg-cyan-50 dark:bg-cyan-500/10'
                            : 'border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:border-slate-400 dark:hover:border-slate-500'
                        }`}
                    >
                        牛熊高阶
                    </button>
                </div>
            </div>
            <div className="flex items-center gap-2 mb-2 shrink-0">
                <button
                    onClick={() => {
                        const next = !showSrRef.current
                        showSrRef.current = next
                        setShowSr(next)
                        if (srData.length) updateSrSeries(srData)
                    }}
                    className={`text-xs px-1.5 py-0.5 rounded border transition-colors ${showSr
                        ? 'border-red-500 text-red-500 bg-red-50 dark:bg-red-500/10'
                        : 'border-slate-200 dark:border-slate-600 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300'
                    }`}
                    title="显示/隐藏支撑压力位"
                >
                    止盈止损
                </button>
                <button
                    onClick={() => {
                        const next = !showTdRef.current
                        showTdRef.current = next
                        setShowTd(next)
                        if (next && tdData.length) renderTdMarkers(tdData)
                        else tdMarkerContainerRef.current && (tdMarkerContainerRef.current.innerHTML = '')
                    }}
                    className={`text-xs px-1.5 py-0.5 rounded border transition-colors ${showTd
                        ? 'border-purple-500 text-purple-500 bg-purple-50 dark:bg-purple-500/10'
                        : 'border-slate-200 dark:border-slate-600 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300'
                    }`}
                    title="显示/隐藏神奇九转"
                >
                    九转
                </button>
            </div>
            <div className="relative flex-1 min-h-0 rounded-md border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 overflow-hidden">
                <div ref={containerRef} className="absolute inset-0" />
                <div ref={srMarkerContainerRef} className="absolute inset-0 pointer-events-none z-10" />
                <div ref={tdMarkerContainerRef} className="absolute inset-0 pointer-events-none z-10" />
                {indicatorMode !== 'off' && (() => {
                    const showNx = indicatorMode === 'niuxiong' || indicatorMode === 'combined'
                    const showGs = indicatorMode === 'gs' || indicatorMode === 'niuxiong' || indicatorMode === 'combined'
                    const activeDate = panelCandle?.date
                    const lastNx = showNx && niuxiongData.length
                        ? niuxiongData.find(p => p.date === activeDate) ?? niuxiongData[niuxiongData.length - 1]
                        : null
                    const lastGs = showGs && gsData.length
                        ? gsData.find(p => p.date === activeDate) ?? gsData[gsData.length - 1]
                        : null
                    if (!lastNx && !lastGs) return null
                    return (
                        <div className="absolute left-3 top-3 max-sm:hidden text-xs px-2 py-1.5 rounded bg-white/80 dark:bg-slate-800/80 text-slate-600 dark:text-slate-400 flex flex-col gap-0.5">
                            {lastNx && (
                                <div className="flex items-center gap-4">
                                    <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-yellow-400" style={{ borderTop: '1px dashed #eab308' }} />决策线 <span className="text-yellow-500 font-medium">{lastNx.decision_line ?? '--'}</span></span>
                                    <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-red-500" style={{ borderTop: '1px dashed #ef4444' }} />牛线 <span className="text-red-500 font-medium">{lastNx.bull_line ?? '--'}</span></span>
                                    {lastNx.bear_line != null && (
                                        <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-green-500" style={{ borderTop: '1px dashed #22c55e' }} />熊线 <span className="text-green-500 font-medium">{lastNx.bear_line}</span></span>
                                    )}
                                    <span className="flex items-center gap-1">
                                        <span className="inline-block w-3 h-0.5 bg-red-700" />
                                        轨道线 <span className="text-red-700 font-medium">{lastNx.orbit_line ?? '--'}</span>
                                    </span>
                                </div>
                            )}
                            {(() => {
                                const lastSr = srData.length
                                    ? srData.find(p => p.date === activeDate) ?? srData[srData.length - 1]
                                    : null
                                if (!lastSr) return null
                                return (
                                    <div className="flex items-center gap-4">
                                        {lastSr.support != null && (
                                            <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-red-500" />支撑 <span className="text-red-500 font-medium">{lastSr.support}</span></span>
                                        )}
                                        {lastSr.resistance != null && (
                                            <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-green-500" />压力 <span className="text-green-500 font-medium">{lastSr.resistance}</span></span>
                                        )}
                                    </div>
                                )
                            })()}
                            {lastGs && (
                                <div className="flex items-center gap-4">
                                    <span className="flex items-center gap-1">
                                        <span className={`inline-block w-2 h-2 rounded-full ${(lastGs.trend_state ?? '').includes('上涨') ? 'bg-red-500' : 'bg-green-500'}`} />
                                        {lastGs.trend_state ?? '--'}
                                    </span>
                                    {lastGs.zj_bias != null && (
                                        <span className="text-slate-500">乖离 {lastGs.zj_bias > 0 ? '+' : ''}{lastGs.zj_bias}%</span>
                                    )}
                                    {lastGs.buy_signal && (
                                        <span className="text-red-500 font-bold">G 信号</span>
                                    )}
                                    {lastGs.sell_signal && (
                                        <span className="text-green-500 font-bold">S 信号</span>
                                    )}
                                </div>
                            )}
                        </div>
                    )
                })()}
                {loading && (
                    <div className="absolute right-3 top-3 text-xs px-2 py-1 rounded bg-white/90 dark:bg-slate-800/90 text-slate-600 dark:text-slate-400 flex items-center gap-1">
                        <Activity className="w-3 h-3 animate-pulse" />
                        加载中
                    </div>
                )}
                {error && (
                    <div className="absolute left-3 top-3 text-xs px-2 py-1 rounded bg-white/90 dark:bg-slate-800/90 text-orange-500">
                        {error}
                    </div>
                )}
            </div>
        </section>
            <DarkPoolDrawer symbol={symbol} stockName={stockName} open={darkPoolOpen} onClose={() => setDarkPoolOpen(false)} />
        </>
        )
}
