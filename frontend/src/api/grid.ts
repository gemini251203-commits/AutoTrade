/**
 * Grid API
 * =========
 * 网格交易相关 API
 * 
 * 端点对照表:
 *   GET    /grid/             -> listGridBots()
 *   POST   /grid/             -> createGridBot()
 *   POST   /grid/{id}/start   -> startGridBot()
 *   POST   /grid/{id}/stop    -> stopGridBot()
 *   GET    /grid/{id}         -> getGridBot()
 *   DELETE /grid/{id}         -> deleteGridBot()
 */

import request from '@/utils/request'

// ==================== Types ====================

/** 网格类型 (对应后端 GridType) */
export type GridType = 'arithmetic' | 'geometric'

/** 网格方向 (对应后端 GridDirection) */
export type GridDirection = 'long' | 'short' | 'neutral'

/** 网格状态 (对应后端 GridStatus) */
export type GridStatus = 'created' | 'running' | 'paused' | 'stopped' | 'completed' | 'error'

/** 创建网格请求 (对应后端 GridCreateRequest) */
export interface GridCreateRequest {
  name: string                       // 机器人名称
  symbol: string                     // 交易对
  lower_price: number | string       // 下限价格
  upper_price: number | string       // 上限价格
  grid_count: number                 // 网格数量 (2-200)
  investment: number | string        // 投入金额 (USDT)
  leverage?: number                  // 杠杆倍数 (默认 1)
  grid_type?: GridType               // 网格类型 (默认 arithmetic)
  direction?: GridDirection          // 网格方向 (默认 long)
  stop_loss_price?: number | string  // 网格止损价
  take_profit_price?: number | string // 网格止盈价
}

/** 启动网格请求 (对应后端 GridStartRequest) */
export interface GridStartRequest {
  current_price: number | string     // 当前价格
}

/** 网格响应 (对应后端 GridResponse) */
export interface GridResponse {
  id: number
  name: string
  symbol: string
  grid_type: GridType
  direction: GridDirection
  status: GridStatus
  upper_price: string       // Decimal -> string
  lower_price: string       // Decimal -> string
  grid_count: number
  investment: string        // Decimal -> string
  leverage: number
  grid_interval: string | null
  quantity_per_grid: string | null
  current_level: number
  filled_buy_count: number
  filled_sell_count: number
  total_profit: string      // Decimal -> string
  realized_pnl: string      // Decimal -> string
  profit_rate: string       // Decimal -> string
  created_at: string        // ISO datetime string
  started_at: string | null // ISO datetime string
}

/** 网格详情响应 (对应后端 GridDetailResponse) */
export interface GridDetailResponse extends GridResponse {
  grid_levels: Record<string, unknown>[] | null
}

// ==================== API Functions ====================

/**
 * 获取用户网格机器人列表
 * 
 * @param statusFilter 可选状态过滤
 * @returns 网格列表
 */
export async function listGridBots(statusFilter?: GridStatus): Promise<GridResponse[]> {
  const params: Record<string, unknown> = {}
  if (statusFilter) {
    params.status_filter = statusFilter
  }
  const response = await request.get<GridResponse[]>('/grid/', { params })
  return response.data
}

/**
 * 创建网格机器人
 * 
 * @param data 创建参数
 * @returns 创建的网格
 */
export async function createGridBot(data: GridCreateRequest): Promise<GridResponse> {
  const response = await request.post<GridResponse>('/grid/', data)
  return response.data
}

/**
 * 启动网格机器人
 * 
 * @param botId 网格 ID
 * @param currentPrice 当前价格
 * @returns 更新后的网格
 */
export async function startGridBot(botId: number, currentPrice: number | string): Promise<GridResponse> {
  const response = await request.post<GridResponse>(`/grid/${botId}/start`, {
    current_price: currentPrice,
  })
  return response.data
}

/**
 * 停止网格机器人
 * 
 * @param botId 网格 ID
 * @param cancelOrders 是否取消挂单 (默认 true)
 * @returns 更新后的网格
 */
export async function stopGridBot(botId: number, cancelOrders: boolean = true): Promise<GridResponse> {
  const response = await request.post<GridResponse>(`/grid/${botId}/stop`, null, {
    params: { cancel_orders: cancelOrders },
  })
  return response.data
}

/**
 * 获取网格详情 (含级别数据)
 * 
 * @param botId 网格 ID
 * @returns 网格详情
 */
export async function getGridBot(botId: number): Promise<GridDetailResponse> {
  const response = await request.get<GridDetailResponse>(`/grid/${botId}`)
  return response.data
}

/**
 * 删除网格机器人 (仅限已停止的)
 * 
 * @param botId 网格 ID
 * @returns 删除结果
 */
export async function deleteGridBot(botId: number): Promise<{ message: string }> {
  const response = await request.delete<{ message: string }>(`/grid/${botId}`)
  return response.data
}
