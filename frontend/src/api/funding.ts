import request from '@/utils/request'

// ==================== 资金费率 ====================

export interface FundingRate {
  symbol: string
  mark_price: string
  funding_rate: string
  funding_rate_pct: string
  annualized_pct: string
  next_funding_time: number
  direction: string
  updated_at?: string
}

export interface FundingRatesResponse {
  rates: FundingRate[]
  count: number
}

export interface FundingHistory {
  symbol: string
  funding_rate: string
  funding_time: number
}

export interface MyFees {
  total_funding_fee: number
  open_position_fees: {
    position_id: number
    symbol: string
    side: string
    size: number
    total_funding_fee: number
  }[]
  recent_transactions: {
    id: number
    amount: number
    balance_after: number
    note: string
    created_at: string
  }[]
}

/** 获取所有交易对当前费率 */
export function getFundingRates() {
  return request.get<FundingRatesResponse>('/funding/rates').then(res => res.data)
}

/** 获取单个交易对详情 */
export function getFundingRateDetail(symbol: string) {
  return request.get<FundingRate>(`/funding/rates/${symbol}`).then(res => res.data)
}

/** 获取历史费率 */
export function getFundingHistory(symbol: string, limit = 100) {
  return request.get<{ symbol: string; history: FundingHistory[]; count: number }>(
    `/funding/history/${symbol}`,
    { params: { limit } }
  ).then(res => res.data)
}

/** 获取用户累计资金费用 */
export function getMyFundingFees() {
  return request.get<MyFees>('/funding/my-fees').then(res => res.data)
}
