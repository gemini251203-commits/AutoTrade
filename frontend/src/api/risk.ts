/**
 * Risk API
 * =========
 * 风控相关 API
 * 
 * 端点对照表:
 *   GET  /risk/positions  -> getPositionsRisk()
 *   GET  /risk/account    -> getAccountRisk()
 *   POST /risk/check      -> triggerRiskCheck()
 */

import request from '@/utils/request'

// ==================== Types ====================

/** 仓位风险数据 (对应后端 PositionRiskResponse) */
export interface PositionRiskResponse {
  position_id: number
  symbol: string
  side: string             // 'long' | 'short'
  size: string             // Decimal -> string
  entry_price: string      // Decimal -> string
  mark_price: string       // Decimal -> string
  leverage: number
  margin: string           // Decimal -> string
  margin_mode: string      // 'cross' | 'isolated'
  liquidation_price: string | null
  is_dynamic_liq: boolean  // true = cross margin (动态强平价)
  unrealized_pnl: string   // Decimal -> string
  roe_percent: string      // Decimal -> string
  margin_ratio: string     // Decimal -> string
  is_at_risk: boolean
  should_liquidate: boolean
  stop_loss: string | null
  take_profit: string | null
}

/** 账户风险汇总 (对应后端 AccountRiskResponse) */
export interface AccountRiskResponse {
  user_id: number
  total_margin: string        // Decimal -> string
  total_unrealized_pnl: string
  total_equity: string
  margin_ratio: string
  positions_at_risk: number
  positions_to_liquidate: number
}

/** 风控检查结果 (对应后端 RiskCheckResponse) */
export interface RiskCheckResponse {
  checked: number
  liquidated: number
  details: string[]
}

// ==================== API Functions ====================

/**
 * 获取仓位风险数据
 * 
 * @param symbol 可选交易对过滤
 * @returns 仓位风险列表
 */
export async function getPositionsRisk(symbol?: string): Promise<PositionRiskResponse[]> {
  const params: Record<string, unknown> = {}
  if (symbol) {
    params.symbol = symbol
  }
  const response = await request.get<PositionRiskResponse[]>('/risk/positions', { params })
  return response.data
}

/**
 * 获取账户整体风险汇总
 * 
 * @returns 账户风险数据
 */
export async function getAccountRisk(): Promise<AccountRiskResponse> {
  const response = await request.get<AccountRiskResponse>('/risk/account')
  return response.data
}

/**
 * 手动触发风控检查
 * 
 * ⚠️ 此接口仅用于测试/管理
 * 
 * @returns 检查结果
 */
export async function triggerRiskCheck(): Promise<RiskCheckResponse> {
  const response = await request.post<RiskCheckResponse>('/risk/check')
  return response.data
}
