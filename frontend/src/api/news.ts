/**
 * News API
 * =============
 * 新闻模块 API 函数
 * 
 * 对应后端路由: /api/news/*
 */
import request from '@/utils/request'

// ==================== 类型定义 ====================

export interface NewsArticle {
  id: number
  source: string
  title: string
  title_zh: string | null
  url: string
  currencies: string[] | null
  news_category: string | null
  sentiment: string | null
  sentiment_score: number | null
  importance: string | null
  votes_positive: number | null
  votes_negative: number | null
  published_at: string
  created_at: string
}

export interface MarketSentiment {
  overall: string
  score: number
  total_articles: number
  positive_count: number
  negative_count: number
  neutral_count: number
  by_category: Record<string, { count: number; avg_score: number }>
  hours: number
  currency: string | null
}

export interface NewsAlert {
  id: number
  user_id: number
  name: string
  keywords: string[]
  news_categories: string[] | null
  currencies: string[] | null
  sentiment_filter: string
  action: string
  trade_side: string | null
  trade_symbol: string | null
  trade_position_pct: number | null
  trade_leverage: number | null
  trade_stop_loss_pct: number | null
  trade_take_profit_pct: number | null
  is_active: boolean
  is_reliable: boolean
  reliability_note: string | null
  triggered_count: number
  win_count: number
  loss_count: number
  total_pnl: number
  win_rate: number
  last_triggered_at: string | null
  created_at: string
}

export interface NewsThinking {
  id: number
  user_id: number
  news_article_id: number
  news_alert_id: number | null
  step_get_news: string | null
  step_analyze: string | null
  step_evaluate: string | null
  step_decide: string | null
  decision: string
  trade_action: Record<string, any> | null
  position_id: number | null
  trade_result: string | null
  trade_pnl: number | null
  ai_reflection: string | null
  created_at: string
}

export interface TradingStats {
  total_trades: number
  win_count: number
  loss_count: number
  win_rate: number
  total_pnl: number
}

export interface CreateAlertParams {
  name: string
  keywords: string[]
  news_categories?: string[]
  currencies?: string[]
  sentiment_filter?: string
  action?: string
  trade_side?: string
  trade_symbol?: string
  trade_position_pct?: number
  trade_leverage?: number
  trade_stop_loss_pct?: number
  trade_take_profit_pct?: number
}

export interface UpdateAlertParams {
  name?: string
  keywords?: string[]
  news_categories?: string[]
  currencies?: string[]
  sentiment_filter?: string
  action?: string
  trade_side?: string
  trade_symbol?: string
  trade_position_pct?: number
  trade_leverage?: number
  trade_stop_loss_pct?: number
  trade_take_profit_pct?: number
  is_active?: boolean
  is_reliable?: boolean
  reliability_note?: string
}

// ==================== API 函数 ====================

/** 获取最新新闻列表 */
export async function getLatestNews(params?: {
  currency?: string
  news_category?: string
  keyword?: string
  limit?: number
}): Promise<NewsArticle[]> {
  const resp = await request.get('/news/articles', { params })
  return resp.data
}

/** 获取市场情绪 */
export async function getMarketSentiment(
  currency: string,
  hours?: number,
): Promise<MarketSentiment> {
  const resp = await request.get(`/news/sentiment/${currency}`, {
    params: hours ? { hours } : undefined,
  })
  return resp.data
}

/** 获取监控规则列表 */
export async function getNewsAlerts(): Promise<NewsAlert[]> {
  const resp = await request.get('/news/alerts')
  return resp.data
}

/** 创建监控规则 */
export async function createNewsAlert(data: CreateAlertParams): Promise<NewsAlert> {
  const resp = await request.post('/news/alerts', data)
  return resp.data
}

/** 更新监控规则 */
export async function updateNewsAlert(
  id: number,
  data: UpdateAlertParams,
): Promise<NewsAlert> {
  const resp = await request.put(`/news/alerts/${id}`, data)
  return resp.data
}

/** 删除监控规则 */
export async function deleteNewsAlert(id: number): Promise<{ message: string }> {
  const resp = await request.delete(`/news/alerts/${id}`)
  return resp.data
}

/** 获取AI思考记录 */
export async function getNewsThinkings(params?: {
  news_article_id?: number
  limit?: number
}): Promise<NewsThinking[]> {
  const resp = await request.get('/news/thinkings', { params })
  return resp.data
}

/** 获取新闻交易绩效 */
export async function getNewsTradingStats(
  alertId?: number,
): Promise<TradingStats> {
  const resp = await request.get('/news/stats', {
    params: alertId ? { alert_id: alertId } : undefined,
  })
  return resp.data
}
