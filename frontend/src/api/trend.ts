/**
 * Trend API
 * =========
 * 趋势分析方案相关 API
 */

import request from '@/utils/request'

// ==================== Types ====================

export interface TrendSchemeResponse {
  id: number
  name: string
  config_yaml: string
  is_active: boolean
  is_preset: boolean
  last_result: TrendResultData | null
  last_run_at: string | null
  created_at: string
}

export interface TrendResultData {
  direction: string
  direction_score: number
  direction_detail: string
  strength: string
  strength_score: number
  volatility: string
  volatility_score: number
  momentum: string
  momentum_score: number
  regime: string
  confidence: number
  suitable_strategies: string[]
  unsuitable_strategies: string[]
  scheme_name: string
  symbol: string
}

export interface TrendSnapshotResponse {
  id: number
  scheme_id: number
  symbol: string
  direction: string
  direction_score: number
  strength: string
  strength_score: number
  volatility: string
  momentum: string
  regime: string
  confidence: number
  suitable_strategies: string[] | null
  created_at: string
}

// ==================== API Functions ====================

/** 列出趋势分析方案 */
export async function listTrendSchemes(): Promise<TrendSchemeResponse[]> {
  const response = await request.get<TrendSchemeResponse[]>('/trend/schemes')
  return response.data
}

/** 创建趋势分析方案 */
export async function createTrendScheme(data: {
  name: string
  config_yaml: string
  is_active?: boolean
}) {
  const response = await request.post('/trend/schemes', data)
  return response.data
}

/** 修改趋势分析方案 */
export async function updateTrendScheme(id: number, data: {
  name?: string
  config_yaml?: string
  is_active?: boolean
}) {
  const response = await request.put(`/trend/schemes/${id}`, data)
  return response.data
}

/** 删除趋势分析方案 */
export async function deleteTrendScheme(id: number) {
  const response = await request.delete(`/trend/schemes/${id}`)
  return response.data
}

/** 手动运行趋势分析 */
export async function runTrendAnalysis(schemeId: number, symbol: string = 'BTCUSDT') {
  const response = await request.post<TrendResultData>(`/trend/schemes/${schemeId}/run`, null, {
    params: { symbol },
  })
  return response.data
}

/** 查看趋势分析历史快照 */
export async function listTrendSnapshots(params?: {
  scheme_id?: number
  symbol?: string
  limit?: number
}): Promise<TrendSnapshotResponse[]> {
  const response = await request.get<TrendSnapshotResponse[]>('/trend/snapshots', { params })
  return response.data
}

/** 初始化预置方案 */
export async function initTrendPresets() {
  const response = await request.post('/trend/init-presets')
  return response.data
}
