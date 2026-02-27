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
