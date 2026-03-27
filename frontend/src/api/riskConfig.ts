/**
 * Risk Config API
 * ================
 * 风控配置中心 API 函数
 */
import request from '@/utils/request'

// ==================== Types ====================

export interface RiskConfigResponse {
  max_leverage: number
  max_daily_loss_pct: number
  risk_percent: number
  default_leverage: number
  max_positions: number
  default_sl_pct: number
  default_tp_pct: number
  kelly_fraction: number
  max_risk_percent: number
  blacklist: string[]
}

export interface RiskConfigUpdateRequest {
  max_leverage?: number
  max_daily_loss_pct?: number
  risk_percent?: number
  default_leverage?: number
  max_positions?: number
  default_sl_pct?: number
  default_tp_pct?: number
  kelly_fraction?: number
  max_risk_percent?: number
  blacklist?: string[]
}

// ==================== API Functions ====================

/** 获取当前风控配置 */
export async function getRiskConfig(): Promise<RiskConfigResponse> {
  const resp = await request.get<RiskConfigResponse>('/risk-config/')
  return resp.data
}

/** 更新风控配置 */
export async function updateRiskConfig(data: RiskConfigUpdateRequest): Promise<RiskConfigResponse> {
  const resp = await request.put<RiskConfigResponse>('/risk-config/', data)
  return resp.data
}

// ==================== Runtime Status ====================

export interface RiskRuntimeStatus {
  circuit_breaker: boolean
  risk_bypass: boolean
  pipeline_active: boolean
  uptime_seconds: number
  active_strategies: number
  recent_verdicts: any[]
}

/** 获取风控运行时状态 */
export async function getRiskStatus(): Promise<RiskRuntimeStatus> {
  const resp = await request.get<RiskRuntimeStatus>('/risk-config/status')
  return resp.data
}

/** 控制熔断器 */
export async function controlCircuitBreaker(action: 'trigger' | 'reset', reason = '') {
  const resp = await request.post('/risk-config/circuit-breaker', { action, reason })
  return resp.data
}

/** 控制风控开关 */
export async function controlRiskBypass(enabled: boolean) {
  const resp = await request.post('/risk-config/risk-bypass', { enabled })
  return resp.data
}

