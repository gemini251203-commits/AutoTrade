/**
 * AI Signal API
 * ==============
 * AI 信号解析相关 API
 * 
 * 端点对照表:
 *   POST /ai/parse-signal      -> parseSignal()
 *   GET  /ai/context/{symbol}  -> getAIContext()
 *   POST /ai/analyze/{symbol}  -> analyzeSymbol()
 */

import request from '@/utils/request'

// ==================== Types ====================

/** 信号解析请求 */
export interface ParseSignalRequest {
  text: string      // 喊单文本
  symbol?: string   // 可选指定币种
}

/** 解析后的信号 */
export interface ParsedSignal {
  // 基础信息
  symbol: string
  side: 'long' | 'short'
  trade_style: 'left_side' | 'right_side' | ''
  
  // 交易模式
  trading_mode: 'left_side' | 'right_side' | 'market'
  
  // 入场价格
  entry_price: number | null
  entry_low: number | null
  entry_high: number | null
  
  // 右侧交易: 突破条件
  trigger_price: number | null
  max_deviation_pct: number | null
  confirm_interval: string
  timeout_hours: number
  condition_type: 'simple_breakout' | 'breakdown_reclaim' | 'breakout_pullback' | null
  
  // 止盈止损
  stop_loss: number | null
  take_profit: number | null
  take_profit_levels: number[]
  
  // 资金管理
  leverage: number
  margin: number | null
  position_percent: number | null
  
  // 分批建仓
  ladder_enabled: boolean
  ladder_count: number
  ladder_ratios: number[]
  ladder_prices: number[]
  
  // 网格参数
  is_grid: boolean
  grid_lower: number | null
  grid_upper: number | null
  grid_count: number | null
  grid_type: 'arithmetic' | 'geometric'
  grid_direction: 'long' | 'short' | 'neutral'
  grid_investment: number | null
  
  // AI 分析
  confidence: number  // 0-1
  reasoning: string
  warnings: string[]
}

/** 信号解析响应 */
export interface ParseSignalResponse {
  success: boolean
  signal: ParsedSignal | null
  context: {
    market: {
      symbol: string
      current_price: number
      price_change_24h: number
      high_24h: number
      low_24h: number
    } | null
    wallet: {
      balance: number
      available: number
      frozen: number
      equity: number
    } | null
    positions_count: number
    pending_orders: number
    running_grids: number
  } | null
  error: string | null
}

/** AI 上下文响应 */
export interface AIContextResponse {
  market: {
    symbol: string
    current_price: number
    price_change_24h: number
    high_24h: number
    low_24h: number
  } | null
  wallet: {
    balance: number
    available: number
    frozen: number
    equity: number
  } | null
  positions: {
    symbol: string
    side: string
    size: number
    entry_price: number
    unrealized_pnl: number
    leverage: number
  }[]
  pending_orders: number
  running_grids: number
  timestamp: string
}

/** 分析响应 */
export interface AnalyzeResponse {
  symbol: string
  current_price: number
  analysis: string
  signal: {
    side: string
    entry_low: number | null
    entry_high: number | null
    stop_loss: number | null
    take_profit: number | null
    confidence: number
  } | null
  warnings: string[]
}

// ==================== API Functions ====================

/**
 * 解析喊单信号
 * 
 * @param text 喊单文本
 * @param symbol 可选指定币种
 * @returns 解析结果
 * 
 * ⚠️ AI 推理可能需要较长时间，使用 60s 超时
 */
export async function parseSignal(text: string, symbol?: string): Promise<ParseSignalResponse> {
  const response = await request.post<ParseSignalResponse>('/ai/parse-signal', {
    text,
    symbol,
  }, {
    timeout: 60000,  // AI 调用需要更长超时 (60s)
  })
  return response.data
}

/**
 * 获取 AI 上下文
 * 
 * @param symbol 交易对
 * @returns 上下文数据
 */
export async function getAIContext(symbol: string): Promise<AIContextResponse> {
  const response = await request.get<AIContextResponse>(`/ai/context/${symbol}`)
  return response.data
}

/**
 * AI 分析交易对
 * 
 * @param symbol 交易对
 * @returns 分析结果
 */
export async function analyzeSymbol(symbol: string): Promise<AnalyzeResponse> {
  const response = await request.post<AnalyzeResponse>(`/ai/analyze/${symbol}`)
  return response.data
}
