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
 *   GET    /journal/            -> getMemories()
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
  decision_interval?: string
}

/** 策略响应 */
export interface StrategyResponse {
  id: number
  user_id: number
  name: string
  symbol: string
  interval: string
  config_yaml: string
  strategy_type: string
  is_active: boolean
  decision_interval: string
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

/** 策略模板 (对应后端 TemplateResponse) */
export interface StrategyTemplate {
  id: string
  name: string
  symbol: string
  interval: string
  config_yaml: string
  strategy_type?: string
  modules?: string
}

/** 交易记忆 (对应后端 journal.py TradeMemoryResponse) */
export interface TradeMemoryResponse {
  id: number
  symbol: string
  source: string | null
  side: string | null
  entry_price: number | null
  exit_price: number | null
  leverage: number | null
  margin_used: number | null
  trade_result: string
  pnl_pct: number
  pnl_usdt: number | null
  duration_minutes: number | null
  close_reason: string | null
  had_stop_loss: boolean | null
  had_take_profit: boolean | null
  open_reason: string | null
  indicators_snapshot: string | null
  lesson: string | null
  strategy_name: string | null
  created_at: string | null
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
export async function updateStrategy(id: number, data: Partial<StrategyRequest>): Promise<StrategyResponse> {
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

/** 手动运行一次策略决策 */
export async function runStrategyOnce(id: number): Promise<{ message: string; reply: string }> {
  const response = await request.post<{ message: string; reply: string }>(`/strategy/${id}/run-once`)
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

/** 获取交易记忆 (调用 journal API) */
export async function getMemories(symbol?: string, limit: number = 50): Promise<TradeMemoryResponse[]> {
  const params: Record<string, unknown> = { limit }
  if (symbol) params.symbol = symbol
  const response = await request.get<TradeMemoryResponse[]>('/journal/', { params })
  return response.data
}

/** 删除单条交易记忆 */
export async function deleteMemory(id: number): Promise<{ ok: boolean }> {
  const response = await request.delete<{ ok: boolean }>(`/journal/${id}`)
  return response.data
}
