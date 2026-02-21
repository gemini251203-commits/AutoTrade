/**
 * Pipeline API
 * ==============
 * 四层流水线管理 API
 * 
 * 端点对照表:
 *   GET  /pipeline/status          -> getPipelineStatus()
 *   GET  /pipeline/config          -> getPipelineConfig()
 *   POST /pipeline/circuit-breaker -> controlCircuitBreaker()
 */

import request from '@/utils/request'

// ==================== Types ====================

export interface LayerStatus {
  name: string         // "Alpha" | "Portfolio" | "Risk" | "Execution"
  status: string       // "active" | "idle" | "error" | "disabled"
  detail: string
  count: number
}

export interface PipelineStatusResponse {
  is_active: boolean
  circuit_breaker: boolean
  uptime_seconds: number
  layers: LayerStatus[]
  stats: Record<string, number>
  recent_insights: Record<string, unknown>[]
  recent_verdicts: Record<string, unknown>[]
}

export interface PipelineConfigResponse {
  portfolio_model: string
  risk_percent: number
  default_leverage: number
  max_positions: number
  max_leverage: number
  max_daily_loss_pct: number
  max_total_exposure_pct: number
  blacklist: string[]
}

export interface CircuitBreakerResponse {
  circuit_breaker: boolean
  message: string
}

// ==================== API Functions ====================

/**
 * 获取 Pipeline 实时状态
 */
export async function getPipelineStatus(): Promise<PipelineStatusResponse> {
  const response = await request.get<PipelineStatusResponse>('/pipeline/status')
  return response.data
}

/**
 * 获取 Pipeline 配置
 */
export async function getPipelineConfig(): Promise<PipelineConfigResponse> {
  const response = await request.get<PipelineConfigResponse>('/pipeline/config')
  return response.data
}

/**
 * 控制熔断器
 */
export async function controlCircuitBreaker(
  action: 'trigger' | 'reset',
  reason: string = ''
): Promise<CircuitBreakerResponse> {
  const response = await request.post<CircuitBreakerResponse>(
    '/pipeline/circuit-breaker',
    { action, reason }
  )
  return response.data
}
