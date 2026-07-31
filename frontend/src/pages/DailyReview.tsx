import { useState, useEffect, useCallback } from 'react'
import { Activity, Play, RefreshCw, TrendingUp, AlertTriangle, CheckCircle, Clock, Loader2 } from 'lucide-react'
import { api } from '@/services/api'

interface ReviewData {
  trade_date?: string
  sentiment_report?: string
  capital_report?: string
  theme_report?: string
  dragon_tiger_report?: string
  leader_report?: string
  macro_sector_report?: string
  tomorrow_focus?: string
  emotion_metrics?: {
    money_effect?: {
      available?: boolean
      median?: number
      avg?: number
      positive_rate?: number
    }
    promotion?: {
      available?: boolean
      overall?: {
        rate?: number
      }
      limit_up_count?: number
    }
    cycle?: {
      available?: boolean
      trend?: string
      day_n?: number
    }
    [key: string]: unknown
  }
  market_facts?: Record<string, unknown>
  focus_struct?: unknown
}

interface ReviewStatus {
  running: boolean
  last_date: string | null
  error: string | null
}

interface OverseasData {
  available?: boolean
  indices?: Array<{name: string; price: string; change_pct: string}>
  mag7?: Array<{name: string; price: string; change_pct: string}>
  us_session?: string
  hk_session?: string
}

export default function DailyReview() {
  const [reviewData, setReviewData] = useState<ReviewData | null>(null)
  const [status, setStatus] = useState<ReviewStatus>({ running: false, last_date: null, error: null })
  const [overseas, setOverseas] = useState<OverseasData | null>(null)
  const [loading, setLoading] = useState(true)
  const [renderError, setRenderError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'overview' | 'sentiment' | 'capital' | 'theme' | 'dragon' | 'leader' | 'focus'>('overview')
  const [chatQuestion, setChatQuestion] = useState('')
  const [chatAnswer, setChatAnswer] = useState('')
  const [chatLoading, setChatLoading] = useState(false)

  // 加载最新复盘数据
  const loadReview = useCallback(async () => {
    try {
      setLoading(true)
      setRenderError(null)
      const data = await api.get('/v1/review/latest') as ReviewData
      setReviewData(data)
    } catch (err) {
      console.error('加载复盘数据失败:', err)
      setReviewData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  // 加载状态
  const loadStatus = useCallback(async () => {
    try {
      const data = await api.get('/v1/review/status') as ReviewStatus
      setStatus(data)
    } catch (err) {
      console.error('加载状态失败:', err)
    }
  }, [])

  // 加载外围数据
  const loadOverseas = useCallback(async () => {
    try {
      const data = await api.get('/v1/review-market/overseas') as OverseasData
      setOverseas(data)
    } catch (err) {
      console.error('加载外围数据失败:', err)
    }
  }, [])

  useEffect(() => {
    loadReview()
    loadStatus()
    loadOverseas()

    // 轮询状态
    const statusInterval = setInterval(loadStatus, 5000)
    return () => clearInterval(statusInterval)
  }, [loadReview, loadStatus, loadOverseas])

  // 运行复盘
  const handleRunReview = async () => {
    try {
      await api.post('/v1/review/run', {})
      // 开始轮询状态
      const interval = setInterval(async () => {
        await loadStatus()
        const currentStatus = await api.get('/v1/review/status') as ReviewStatus
        if (!currentStatus.running) {
          clearInterval(interval)
          await loadReview()
        }
      }, 3000)
    } catch (err) {
      console.error('运行复盘失败:', err)
    }
  }

  // 发送对话
  const handleChat = async () => {
    if (!chatQuestion.trim()) return
    try {
      setChatLoading(true)
      const data = await api.post('/v1/review/chat', { question: chatQuestion }) as { answer: string }
      setChatAnswer(data.answer)
    } catch (err) {
      console.error('对话失败:', err)
      setChatAnswer('对话失败，请先运行复盘')
    } finally {
      setChatLoading(false)
    }
  }

  // 情绪指标卡片
  const EmotionCard = ({ label, value, status: s }: { label: string; value: string; status?: string }) => (
    <div className="bg-white dark:bg-gray-800 rounded-lg p-3 md:p-4 border border-gray-200 dark:border-gray-700">
      <div className="text-xs md:text-sm text-gray-500 dark:text-gray-400">{label}</div>
      <div className="text-lg md:text-2xl font-bold mt-1">{value}</div>
      {s && (
        <div className={`text-xs mt-1 ${s === '亢奋' ? 'text-red-500' : s === '退潮' ? 'text-green-500' : 'text-yellow-500'}`}>
          {s}
        </div>
      )}
    </div>
  )

  // 报告区块
  const ReportSection = ({ title, content }: { title: string; content: string }) => (
    <div className="bg-white dark:bg-gray-800 rounded-lg p-4 md:p-6 border border-gray-200 dark:border-gray-700">
      <h3 className="text-base md:text-lg font-semibold mb-3 md:mb-4 flex items-center gap-2">
        <Activity className="w-4 h-4 md:w-5 md:h-5 text-blue-500" />
        {title}
      </h3>
      <div className="prose dark:prose-invert max-w-none whitespace-pre-wrap text-xs md:text-sm leading-relaxed">
        {content || '暂无数据，请先运行复盘'}
      </div>
    </div>
  )

  // 渲染错误处理
  if (renderError) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-center">
          <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <h2 className="text-lg font-semibold mb-2">渲染错误</h2>
          <p className="text-gray-500 mb-4">{renderError}</p>
          <button onClick={() => { setRenderError(null); loadReview(); }} className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600">
            重试
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4 md:space-y-6">
      {/* 页面标题和操作栏 */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <h1 className="text-xl md:text-2xl font-bold flex items-center gap-2">
            <TrendingUp className="w-6 h-6 md:w-7 md:h-7 text-blue-500" />
            短线复盘
          </h1>
          <p className="text-sm md:text-base text-gray-500 dark:text-gray-400 mt-1">
            A股短线情绪分析 · 五分析师收敛 · 每日复盘看板
          </p>
        </div>
        <div className="flex items-center gap-2 md:gap-3">
          {/* 状态指示 */}
          {status.running && (
            <div className="flex items-center gap-2 text-blue-500">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span className="text-sm">运行中...</span>
            </div>
          )}
          {status.error && (
            <div className="flex items-center gap-2 text-red-500">
              <AlertTriangle className="w-4 h-4" />
              <span className="text-sm">出错</span>
            </div>
          )}
          {/* 运行按钮 */}
          <button
            onClick={handleRunReview}
            disabled={status.running}
            className="flex items-center gap-1 md:gap-2 px-3 md:px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm"
          >
            {status.running ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="hidden md:inline">运行中...</span>
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                <span className="hidden md:inline">运行复盘</span>
                <span className="md:hidden">运行</span>
              </>
            )}
          </button>
          <button
            onClick={loadReview}
            className="flex items-center gap-1 md:gap-2 px-2 md:px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors text-sm"
          >
            <RefreshCw className="w-4 h-4" />
            <span className="hidden md:inline">刷新</span>
          </button>
        </div>
      </div>

      {/* 交易日期 */}
      {reviewData?.trade_date && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Clock className="w-4 h-4" />
          交易日: {reviewData.trade_date}
        </div>
      )}

      {/* Tab 导航 */}
      <div className="border-b border-gray-200 dark:border-gray-700 overflow-x-auto">
        <nav className="flex gap-4 md:gap-6 min-w-max">
          {[
            { key: 'overview', label: '总览' },
            { key: 'sentiment', label: '情绪面' },
            { key: 'capital', label: '资金面' },
            { key: 'theme', label: '题材热点' },
            { key: 'dragon', label: '龙虎榜' },
            { key: 'leader', label: '龙头跟踪' },
            { key: 'focus', label: '明日关注' },
          ].map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key as typeof activeTab)}
              className={`py-2 md:py-3 px-1 border-b-2 text-xs md:text-sm font-medium transition-colors whitespace-nowrap ${
                activeTab === tab.key
                  ? 'border-blue-500 text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* 内容区 */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
        </div>
      ) : (
        <div className="space-y-6">
          {/* 总览 */}
          {activeTab === 'overview' && (
            <>
              {/* 情绪指标卡片 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <EmotionCard
                  label="赚钱效应"
                  value={reviewData?.emotion_metrics?.money_effect?.median != null ? `${Number(reviewData.emotion_metrics.money_effect.median) > 0 ? '+' : ''}${reviewData.emotion_metrics.money_effect.median}%` : '--'}
                  status={Number(reviewData?.emotion_metrics?.money_effect?.median ?? 0) > 0 ? '回暖' : '低迷'}
                />
                <EmotionCard
                  label="晋级率"
                  value={reviewData?.emotion_metrics?.promotion?.overall?.rate != null ? `${(Number(reviewData.emotion_metrics.promotion.overall.rate) * 100).toFixed(1)}%` : '--'}
                />
                <EmotionCard
                  label="涨停家数"
                  value={reviewData?.emotion_metrics?.promotion?.limit_up_count != null ? String(reviewData.emotion_metrics.promotion.limit_up_count) : '--'}
                />
                <EmotionCard
                  label="情绪周期"
                  value={reviewData?.emotion_metrics?.cycle?.trend || '--'}
                />
              </div>

              {/* 外围市场 */}
              {overseas?.available && Array.isArray(overseas.indices) && overseas.indices.length > 0 && (
                <div className="bg-white dark:bg-gray-800 rounded-lg p-3 md:p-4 border border-gray-200 dark:border-gray-700">
                  <h3 className="font-semibold mb-2 md:mb-3 text-sm md:text-base">隔夜外围</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 md:gap-4 text-xs md:text-sm">
                    {overseas.indices.map((item: {name?: string; price?: string | number; change_pct?: string | number}, idx: number) => (
                      <div key={idx}>
                        <span className="text-gray-500">{item.name || '--'}: </span>
                        <span className={String(item.change_pct || '').startsWith('-') ? 'text-green-500' : 'text-red-500'}>
                          {item.price || '--'} ({item.change_pct || '--'}%)
                        </span>
                      </div>
                    ))}
                  </div>
                  {Array.isArray(overseas.mag7) && overseas.mag7.length > 0 && (
                    <div className="mt-2 md:mt-3 pt-2 md:pt-3 border-t border-gray-200 dark:border-gray-700">
                      <h4 className="text-xs md:text-sm font-medium mb-2">美股七姐妹</h4>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 md:gap-4 text-xs md:text-sm">
                        {overseas.mag7.map((item: {name?: string; price?: string | number; change_pct?: string | number}, idx: number) => (
                          <div key={idx}>
                            <span className="text-gray-500">{item.name || '--'}: </span>
                            <span className={String(item.change_pct || '').startsWith('-') ? 'text-green-500' : 'text-red-500'}>
                              {item.price || '--'} ({item.change_pct || '--'}%)
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* 明天关注（摘要） */}
              {reviewData?.tomorrow_focus && (
                <div className="bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/20 dark:to-indigo-900/20 rounded-lg p-6 border border-blue-200 dark:border-blue-800">
                  <h3 className="font-semibold mb-3 flex items-center gap-2">
                    <CheckCircle className="w-5 h-5 text-blue-500" />
                    明天关注
                  </h3>
                  <div className="prose dark:prose-invert max-w-none text-sm">
                    {reviewData.tomorrow_focus}
                  </div>
                </div>
              )}
            </>
          )}

          {/* 各分栏内容 */}
          {activeTab === 'sentiment' && <ReportSection title="情绪面分析" content={reviewData?.sentiment_report || ''} />}
          {activeTab === 'capital' && <ReportSection title="资金面分析" content={reviewData?.capital_report || ''} />}
          {activeTab === 'theme' && <ReportSection title="题材热点" content={reviewData?.theme_report || ''} />}
          {activeTab === 'dragon' && <ReportSection title="龙虎榜游资" content={reviewData?.dragon_tiger_report || ''} />}
          {activeTab === 'leader' && <ReportSection title="龙头跟踪" content={reviewData?.leader_report || ''} />}
          {activeTab === 'focus' && <ReportSection title="明天关注点" content={reviewData?.tomorrow_focus || ''} />}
        </div>
      )}

      {/* 对话区 */}
      <div className="bg-white dark:bg-gray-800 rounded-lg p-4 md:p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="font-semibold mb-3 md:mb-4 text-sm md:text-base">💬 复盘对话</h3>
        <div className="flex gap-2 md:gap-3">
          <input
            type="text"
            value={chatQuestion}
            onChange={e => setChatQuestion(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleChat()}
            placeholder="基于复盘数据提问..."
            className="flex-1 px-3 md:px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
          />
          <button
            onClick={handleChat}
            disabled={chatLoading}
            className="px-3 md:px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 transition-colors text-sm"
          >
            {chatLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : '发送'}
          </button>
        </div>
        {chatAnswer && (
          <div className="mt-3 md:mt-4 p-3 md:p-4 bg-gray-50 dark:bg-gray-700 rounded-lg prose dark:prose-invert max-w-none text-xs md:text-sm">
            {chatAnswer}
          </div>
        )}
      </div>
    </div>
  )
}
