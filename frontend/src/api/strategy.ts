/**
 * Strategy API
 * =============
 * 量化策略相关 API
 * 
 * 端点对照表:
 *   GET    /strategy/           -> listStrategies()
 *   POST   /strategy/           -> createStrategy()
 *   PUT    /strategy/{id}       -> updateStrategy()
 *   DELETE /strategy/{id}       -> deleteStrategy()
 *   POST   /strategy/{id}/start -> startStrategy()
 *   POST   /strategy/{id}/stop  -> stopStrategy()
 *   GET    /strategy/{id}/logs  -> getStrategyLogs()
 *   GET    /strategy/templates  -> getTemplates()
 *   GET    /strategy/memories   -> getMemories()
 */

import request from '@/utils/request'

// ==================== Types ====================

/** 策略状态 */
export type StrategyStatus = 'active' | 'inactive'

/** 策略创建/更新请求 */
export interface StrategyRequest {
  name: string
  symbol: string
  interval?: string
  config_yaml: string
}

/** 策略响应 */
export interface StrategyResponse {
  id: number
  user_id: number
  name: string
  symbol: string
  interval: string
  config_yaml: string
  is_active: boolean
  last_run_at: string | null
  last_signal: string | null
  total_trades: number
  win_trades: number
  total_pnl: number
  created_at: string
  updated_at: string
}

/** 策略日志 */
export interface StrategyLogResponse {
  id: number
  strategy_id: number
  signal_type: string
  action: string
  side: string | null
  ai_approve: boolean | null
  ai_confidence: number | null
  ai_reason: string | null
  risk_passed: boolean | null
  risk_reason: string | null
  order_id: number | null
  pnl: number | null
  created_at: string
}

/** 策略模板 */
export interface StrategyTemplate {
  name: string
  description: string
  yaml: string
}

/** 交易记忆 */
export interface TradeMemoryResponse {
  id: number
  symbol: string
  strategy_name: string | null
  trade_result: string
  pnl_pct: number
  situation: string
  lesson: string
  created_at: string
}

// ==================== API Functions ====================

/** 获取用户策略列表 */
export async function listStrategies(): Promise<StrategyResponse[]> {
  const response = await request.get<StrategyResponse[]>('/strategy/')
  return response.data
}

/** 创建策略 */
export async function createStrategy(data: StrategyRequest): Promise<StrategyResponse> {
  const response = await request.post<StrategyResponse>('/strategy/', data)
  return response.data
}

/** 更新策略 */
export async function updateStrategy(id: number, data: StrategyRequest): Promise<StrategyResponse> {
  const response = await request.put<StrategyResponse>(`/strategy/${id}`, data)
  return response.data
}

/** 删除策略 */
export async function deleteStrategy(id: number): Promise<{ message: string }> {
  const response = await request.delete<{ message: string }>(`/strategy/${id}`)
  return response.data
}

/** 启动策略自动交易 */
export async function startStrategy(id: number): Promise<StrategyResponse> {
  const response = await request.post<StrategyResponse>(`/strategy/${id}/start`)
  return response.data
}

/** 停止策略自动交易 */
export async function stopStrategy(id: number): Promise<StrategyResponse> {
  const response = await request.post<StrategyResponse>(`/strategy/${id}/stop`)
  return response.data
}

/** 获取策略执行日志 */
export async function getStrategyLogs(id: number, limit: number = 20): Promise<StrategyLogResponse[]> {
  const response = await request.get<StrategyLogResponse[]>(`/strategy/${id}/logs`, {
    params: { limit },
  })
  return response.data
}

/** 获取策略模板列表 */
export async function getTemplates(): Promise<StrategyTemplate[]> {
  const response = await request.get<StrategyTemplate[]>('/strategy/templates')
  return response.data
}

/** 获取交易记忆 */
export async function getMemories(symbol?: string, limit: number = 20): Promise<TradeMemoryResponse[]> {
  const params: Record<string, unknown> = { limit }
  if (symbol) params.symbol = symbol
  const response = await request.get<TradeMemoryResponse[]>('/strategy/memories', { params })
  return response.data
}
