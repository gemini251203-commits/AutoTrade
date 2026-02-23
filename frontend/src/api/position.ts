/**
 * Position API
 * =============
 * 仓位管理 API 函数
 */
import request from '@/utils/request'

// ==================== Types ====================

/** 仓位响应 (对应后端 PositionResponse) */
export interface PositionResponse {
  id: number
  user_id: number
  symbol: string
  side: string              // 'long' | 'short'
  status: string            // 'open' | 'closed' | 'liquidated'
  size: string              // Decimal → string
  entry_price: string       // Decimal → string
  leverage: number
  margin: string            // Decimal → string
  margin_mode: string       // 'cross' | 'isolated'
  liquidation_price: string | null
  stop_loss: string | null
  take_profit: string | null
  realized_pnl: string      // Decimal → string
  created_at: string
}

/** 带未实现盈亏的仓位响应 (对应后端 PositionWithPnlResponse) */
export interface PositionWithPnlResponse extends PositionResponse {
  unrealized_pnl: string | null  // Decimal → string
  roe_percent: string | null     // Decimal → string
}

// ==================== API Functions ====================

/**
 * 设置止盈止损
 * 
 * @param positionId 仓位 ID
 * @param params 止盈止损参数
 * @returns 更新后的仓位信息
 */
export async function setPositionTpSl(
  positionId: number,
  params: {
    stop_loss?: string | null
    take_profit?: string | null
    mark_price?: string
  }
) {
  const resp = await request.post(`/position/${positionId}/tp-sl`, params)
  return resp.data
}

/**
 * 平仓 (支持部分平仓)
 * 
 * @param positionId 仓位 ID
 * @param params 平仓参数
 * @returns 平仓结果 (含 realized_pnl)
 */
export async function closePosition(
  positionId: number,
  params: {
    close_price: string
    quantity?: string  // 不传则全平
  }
) {
  const resp = await request.post(`/position/${positionId}/close`, params)
  return resp.data
}

/**
 * 计算预计盈亏
 * 
 * @param side 仓位方向 'long' | 'short'
 * @param quantity 平仓数量
 * @param entryPrice 开仓价
 * @param closePrice 平仓价
 * @returns 预计盈亏 (USDT)
 */
export function calculatePnl(
  side: string,
  quantity: number,
  entryPrice: number,
  closePrice: number
): number {
  if (side === 'long') {
    return (closePrice - entryPrice) * quantity
  } else {
    return (entryPrice - closePrice) * quantity
  }
}
