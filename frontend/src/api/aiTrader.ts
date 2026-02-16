/**
 * AI Trader API
 * ==============
 * AI 自主交易机器人 API
 * 
 * 端点对照表:
 *   GET    /ai-trader/status           -> getStatus()
 *   POST   /ai-trader/start            -> start()
 *   POST   /ai-trader/stop             -> stop()
 *   POST   /ai-trader/run-once         -> runOnce()
 *   GET    /ai-trader/decisions        -> getDecisions()
 *   GET    /ai-trader/decisions/{id}   -> getDecisionDetail()
 *   GET    /ai-trader/config           -> getConfig()
 *   PUT    /ai-trader/config           -> updateConfig()
 */

import request from '@/utils/request'

// ==================== Types ====================

export interface AITraderConfig {
  enabled: boolean
  symbols: string[]
  interval: string
  max_position_pct: number
  max_leverage: number
  min_confidence: number
}

export interface AITraderStatus {
  running: boolean
  enabled: boolean
  config: AITraderConfig | null
  total_decisions: number
  total_executed: number
  latest_decision_at: string | null
}

export interface Decision {
  id: number
  symbol: string
  cycle_no: number
  action: string
  reasoning: string
  confidence: number
  executed: boolean
  order_id: number | null
  reject_reason: string | null
  market_snapshot: Record<string, any> | null
  account_snapshot: Record<string, any> | null
  risk_params: Record<string, any> | null
  experience_used: Record<string, any> | null
  created_at: string
}

// ==================== API ====================

/** 获取运行状态 */
export function getStatus() {
  return request.get<AITraderStatus>('/ai-trader/status')
}

/** 启动 AI Trader */
export function start() {
  return request.post('/ai-trader/start')
}

/** 停止 AI Trader */
export function stop() {
  return request.post('/ai-trader/stop')
}

/** 手动触发一次决策 */
export function runOnce(symbol: string = 'BTCUSDT') {
  return request.post(`/ai-trader/run-once?symbol=${symbol}`)
}

/** 获取决策历史 */
export function getDecisions(params?: {
  symbol?: string
  action?: string
  executed_only?: boolean
  page?: number
  size?: number
}) {
  return request.get<Decision[]>('/ai-trader/decisions', { params })
}

/** 获取单条决策详情 */
export function getDecisionDetail(id: number) {
  return request.get<Decision>(`/ai-trader/decisions/${id}`)
}

/** 获取配置 */
export function getConfig() {
  return request.get<AITraderConfig>('/ai-trader/config')
}

/** 更新配置 */
export function updateConfig(config: AITraderConfig) {
  return request.put<AITraderConfig>('/ai-trader/config', config)
}
