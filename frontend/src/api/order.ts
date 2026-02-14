/**
 * Order API
 * ==========
 * 订单相关 API
 * 
 * 端点对照表:
 *   POST /order/               -> createOrder()
 *   GET  /order/               -> listOrders()
 *   POST /order/{id}/cancel    -> cancelOrder()
 *   POST /order/tp-sl-preview  -> previewTpSl()
 *   POST /order/leverage-info  -> getLeverageInfo()
 */

import request from '@/utils/request'

// ==================== Types ====================

/** 止盈止损预览请求 */
export interface TpSlPreviewRequest {
  symbol: string          // 交易对 (如 BTCUSDT)
  side: string            // "long" 或 "short"
  quantity: string        // 数量 (字符串,避免精度问题)
  entry_price: string     // 入场价格
  take_profit?: string    // 止盈价格 (可选)
  stop_loss?: string      // 止损价格 (可选)
  leverage: number        // 杠杆倍数
}

/** 止盈止损预览响应 */
export interface TpSlPreviewResponse {
  take_profit_pnl: number   // 止盈盈亏 (USDT)
  take_profit_pct: number   // 止盈收益率 (%)
  stop_loss_pnl: number     // 止损盈亏 (USDT)
  stop_loss_pct: number     // 止损收益率 (%)
  risk_reward_ratio: number // 风险回报比
  margin_required: number   // 所需保证金
  notional: number          // 名义价值
}

/** 杠杆信息请求 */
export interface LeverageInfoRequest {
  symbol: string           // 交易对
  notional?: string        // 名义价值 (可选)
  quantity?: string        // 数量 (可选)
  price?: string           // 价格 (可选)
}

/** 杠杆信息响应 */
export interface LeverageInfoResponse {
  symbol: string              // 交易对
  max_leverage: number        // 最大杠杆
  maintenance_margin_rate: number  // 维持保证金率 (%)
  notional: number            // 名义价值
  min_notional: number        // 最小名义价值
}

// ==================== API Functions ====================

/**
 * 止盈止损盈亏预览
 * 
 * @param params 预览参数
 * @returns 预计盈亏数据
 */
export async function previewTpSl(params: TpSlPreviewRequest): Promise<TpSlPreviewResponse> {
  const response = await request.post<TpSlPreviewResponse>('/order/tp-sl-preview', params)
  return response.data
}

/**
 * 查询杠杆信息
 * 
 * @param params 查询参数
 * @returns 杠杆限制信息
 */
export async function getLeverageInfo(params: LeverageInfoRequest): Promise<LeverageInfoResponse> {
  const response = await request.post<LeverageInfoResponse>('/order/leverage-info', params)
  return response.data
}
