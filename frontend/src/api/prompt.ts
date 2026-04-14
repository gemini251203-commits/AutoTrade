/**
 * Prompt Template API
 * ====================
 * 提示词模板管理 API Client
 *
 * 端点对照表:
 *   GET    /prompts/templates                         -> listTemplates()
 *   POST   /prompts/templates                         -> createTemplate()
 *   PUT    /prompts/templates/{id}                    -> updateTemplate()
 *   DELETE /prompts/templates/{id}                    -> deleteTemplate()
 *   POST   /prompts/templates/{id}/activate           -> activateTemplate()
 *   POST   /prompts/templates/{id}/deactivate         -> deactivateTemplate()
 *   GET    /prompts/templates/{id}/performance        -> getTemplatePerformance()
 *   POST   /prompts/templates/{id}/duplicate          -> duplicateTemplate()
 *   GET    /prompts/recommend                         -> recommendTemplate()
 */

import request from '@/utils/request'

// ==================== Types ====================

/** 市况标签 */
export type MarketTag =
  | 'trending_up'      // 趋势上涨
  | 'trending_down'    // 趋势下跌
  | 'sideways'         // 横盘震荡
  | 'high_volatility'  // 剧烈波动
  | 'small_fund'       // 小资金 (<1000U)
  | 'medium_fund'      // 中资金 (1000-10000U)
  | 'large_fund'       // 大资金 (>10000U)

/** 提示词模板 */
export interface PromptTemplate {
  id: number
  name: string
  version: number
  description: string | null
  strategy_prompt: string
  risk_rules: string
  behavior_directives: string
  raw_prompt: string
  is_structured: boolean
  market_tags: MarketTag[] | null
  parent_id: number | null
  is_preset: boolean
  total_trades: number
  win_trades: number
  total_pnl: number
  win_rate: number
  active_hours: number
  created_at: string
  updated_at: string
}

/** 创建请求 */
export interface PromptTemplateCreateRequest {
  name: string
  description?: string | null
  strategy_prompt?: string
  risk_rules?: string
  behavior_directives?: string
  raw_prompt?: string
  is_structured?: boolean
  market_tags?: MarketTag[] | null
  parent_id?: number | null
}

/** 更新请求 */
export interface PromptTemplateUpdateRequest {
  name?: string
  description?: string | null
  strategy_prompt?: string
  risk_rules?: string
  behavior_directives?: string
  raw_prompt?: string
  is_structured?: boolean
  market_tags?: MarketTag[] | null
}

/** 收益表现 */
export interface TemplatePerformance {
  template_id: number
  total_trades: number
  win_trades: number
  loss_trades: number
  total_pnl: number
  win_rate: number
}

// ==================== API Functions ====================

/** 列出模板 */
export function listTemplates(includePresets: boolean = true) {
  return request.get<{ templates: PromptTemplate[]; total: number }>(
    '/prompts/templates',
    { params: { include_presets: includePresets } },
  ).then(res => res.data)
}

/** 创建模板 */
export function createTemplate(data: PromptTemplateCreateRequest) {
  return request.post<PromptTemplate>('/prompts/templates', data).then(res => res.data)
}

/** 更新模板 */
export function updateTemplate(templateId: number, data: PromptTemplateUpdateRequest) {
  return request.put<PromptTemplate>(`/prompts/templates/${templateId}`, data).then(res => res.data)
}

/** 删除模板 */
export function deleteTemplate(templateId: number) {
  return request.delete(`/prompts/templates/${templateId}`).then(res => res.data)
}

/** 激活模板到指定 Agent */
export function activateTemplate(templateId: number, agentId: number, reason?: string) {
  return request.post(`/prompts/templates/${templateId}/activate`, {
    agent_id: agentId,
    reason,
  }).then(res => res.data)
}

/** 取消模板绑定 */
export function deactivateTemplate(templateId: number, agentId: number) {
  return request.post(`/prompts/templates/${templateId}/deactivate`, {
    agent_id: agentId,
  }).then(res => res.data)
}

/** 获取模板收益表现 */
export function getTemplatePerformance(templateId: number) {
  return request.get<TemplatePerformance>(`/prompts/templates/${templateId}/performance`).then(res => res.data)
}

/** 复制模板 */
export function duplicateTemplate(templateId: number) {
  return request.post<PromptTemplate>(`/prompts/templates/${templateId}/duplicate`).then(res => res.data)
}

/** 市况推荐 */
export function recommendTemplate(marketRegime?: string, fundSize?: number) {
  return request.get<{ recommendation: PromptTemplate | null; message: string }>(
    '/prompts/recommend',
    { params: { market_regime: marketRegime, fund_size: fundSize } },
  ).then(res => res.data)
}
