import request from '@/utils/request'

// ==================== 资金费率 ====================

export interface FundingRate {
  symbol: string
  markPrice: string
  fundingRate: string
  fundingRatePct: string
  annualizedPct: string
  nextFundingTime: number
  direction: string
  updated_at?: string
}

export interface FundingRatesResponse {
  rates: FundingRate[]
  count: number
}

export interface FundingHistory {
  symbol: string
  fundingRate: string
  fundingTime: number
}

export interface MyFees {
  total_funding_fee: number
  open_position_fees: {
    position_id: number
    symbol: string
    side: string
    size: number
    accumulated_funding_fee: number
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
  return request.get<FundingRatesResponse>('/api/funding/rates')
}

/** 获取单个交易对详情 */
export function getFundingRateDetail(symbol: string) {
  return request.get<FundingRate>(`/api/funding/rates/${symbol}`)
}

/** 获取历史费率 */
export function getFundingHistory(symbol: string, limit = 100) {
  return request.get<{ symbol: string; history: FundingHistory[]; count: number }>(
    `/api/funding/history/${symbol}`,
    { params: { limit } }
  )
}

/** 获取用户累计资金费用 */
export function getMyFundingFees() {
  return request.get<MyFees>('/api/funding/my-fees')
}
