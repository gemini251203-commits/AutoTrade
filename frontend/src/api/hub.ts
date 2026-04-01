/**
 * Agent Hub API
 * ==============
 * 智能体中枢 API Client
 * 
 * 端点对照表:
 *   GET    /hub/agents                     -> listHubAgents()
 *   POST   /hub/agents                     -> createHubAgent()
 *   PUT    /hub/agents/{id}                -> updateHubAgent()
 *   DELETE /hub/agents/{id}                -> deleteHubAgent()
 *   POST   /hub/agents/{id}/activate       -> controlHubAgent()
 *   GET    /hub/status                     -> getHubStatus()
 *   POST   /hub/agents/{id}/chat           -> streamChatWithAgent() (SSE)
 *   POST   /hub/board/deliberate           -> boardDeliberate()
 */

import request from '@/utils/request'
import { getAuthToken } from '@/utils/request'

// ==================== Tool Types ====================

/** 单个工具信息 */
export interface ToolInfo {
  name: string
  description: string
  category: string
  access_type: 'read' | 'execute'
  parameters: Array<{ name: string; type: string; default?: string; required: boolean }>
}

/** 工具全集响应 */
export interface ToolListResponse {
  tools: ToolInfo[]
  total: number
  categories: Record<string, number>
}

/** 获取系统所有工具 */
export function listAllTools() {
  return request.get<ToolListResponse>('/tools/')
}

// ==================== Types (1:1 mirror of Pydantic) ====================

/** 智能体状态 */
export type HubAgentStatus = 'idle' | 'active' | 'paused' | 'error'

/** 智能体 */
export interface HubAgent {
  id: number
  name: string
  role: string
  avatar: string
  provider: string
  model: string
  api_base_url: string | null
  has_api_key: boolean
  system_prompt: string
  temperature: number
  status: HubAgentStatus
  is_active: boolean
  last_run_at: string | null
  last_error: string | null
  total_runs: number
  total_trades: number
  polling_interval: number
  allowed_tools: string[] | null
  active_template_id: number | null
  created_at: string
  updated_at: string
}

/** 创建请求 */
export interface HubAgentCreateRequest {
  name: string
  role?: string
  avatar?: string
  provider?: string
  model?: string
  api_base_url?: string | null
  api_key?: string | null
  system_prompt?: string
  temperature?: number
  polling_interval?: number
  allowed_tools?: string[] | null
}

/** 更新请求 */
export interface HubAgentUpdateRequest {
  name?: string
  role?: string
  avatar?: string
  provider?: string
  model?: string
  api_base_url?: string | null
  api_key?: string | null
  system_prompt?: string
  temperature?: number
  polling_interval?: number
  allowed_tools?: string[] | null
  active_template_id?: number | null
}

/** Hub 全局状态 */
export interface HubStatus {
  mode: 'idle' | 'dictator' | 'board'
  active_count: number
  total_agents: number
  active_agents: HubAgent[]
}

/** 董事会结果 */
export interface BoardOpinion {
  agent_id: number
  agent_name: string
  avatar: string
  decision: string
  confidence: number
  reasoning: string
}

export interface BoardConsensus {
  decision: string
  confidence: number
  vote_count: string
  executed: boolean
  order_id: number | null
}

export interface BoardResult {
  opinions: BoardOpinion[]
  consensus: BoardConsensus
}

// ==================== API Functions ====================

/** 列出智能体 */
export function listHubAgents() {
  return request.get<{ agents: HubAgent[] }>('/hub/agents')
}

/** 创建智能体 */
export function createHubAgent(data: HubAgentCreateRequest) {
  return request.post<HubAgent>('/hub/agents', data)
}

/** 更新智能体 */
export function updateHubAgent(agentId: number, data: HubAgentUpdateRequest) {
  return request.put<HubAgent>(`/hub/agents/${agentId}`, data)
}

/** 删除智能体 */
export function deleteHubAgent(agentId: number) {
  return request.delete(`/hub/agents/${agentId}`)
}

/** 控制智能体 (start/stop/run_once) */
export function controlHubAgent(agentId: number, action: string) {
  return request.post<HubAgent>(`/hub/agents/${agentId}/activate`, { action })
}

/** 日志条目 */
export interface HubLogEntry {
  id: number
  agent_id: number | null
  agent_name: string
  log_type: string
  content: string
  created_at: string
}

/** 获取历史日志 */
export function getHubLogs(params?: { limit?: number; offset?: number; keyword?: string; agent_id?: number }) {
  return request.get<{ logs: HubLogEntry[] }>('/hub/logs', { params })
}

/** 保存一条日志 */
export function saveHubLog(data: { agent_id?: number | null; agent_name?: string; log_type?: string; content: string }) {
  return request.post('/hub/logs', data)
}

/** 获取 Hub 全局状态 */
export function getHubStatus() {
  return request.get<HubStatus>('/hub/status')
}

/** 董事会辩论 */
export function boardDeliberate(topic: string, symbol: string = 'BTCUSDT') {
  return request.post<BoardResult>('/hub/board/deliberate', { topic, symbol })
}

// chatWithAgent() 已移除: EventSource 只支持 GET，但后端是 POST。
// 请使用 streamChatWithAgent() (fetch POST + ReadableStream)。

/**
 * SSE 对话 (fetch 方式, 支持 POST body)
 */
export async function* streamChatWithAgent(
  agentId: number,
  message: string
): AsyncGenerator<{ type: string; content?: string; tool?: string; args?: any; result?: string }> {
  const token = getAuthToken()
  const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
  
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 300_000) // 300s 超时 (deepseek 等模型回复较长)
  
  try {
  const response = await fetch(`${baseUrl}/api/hub/agents/${agentId}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({ message }),
    signal: controller.signal,
  })
  
  if (!response.ok || !response.body) {
    throw new Error(`SSE 连接失败: ${response.status}`)
  }
  
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6))
          yield data
        } catch {
          // ignore parse errors
        }
      }
    }
  }
  } finally {
    clearTimeout(timeout)
  }
}

// ==================== Memory Consolidator ====================

/** 手动触发记忆坍缩 — 立刻生成今日复盘 */
export function triggerConsolidation() {
  return request.post<{
    success: boolean
    summary: string
    key_lessons: string
    importance: number
  }>('/hub/memory/consolidate', null, {
    timeout: 180_000,  // 180s — AI 生成纪要需要较长时间
  })
}

/** 获取近 N 天董事会纪要 */
export function getBoardMinutes(days: number = 7) {
  return request.get<{
    minutes: Array<{
      id: number
      date: string
      summary: string
      key_lessons: string
      importance: number
      trade_count: number
      pnl_total: number
      created_at: string
    }>
  }>('/hub/memory/minutes', { params: { days } })
}

/** 获取指定月份的董事会纪要 (日历视图用) */
export function getMonthlyMinutes(year: number, month: number) {
  return request.get<{
    minutes: Array<{
      id: number
      date: string
      summary: string
      key_lessons: string
      importance: number
      trade_count: number
      pnl_total: number
      created_at: string
    }>
  }>('/hub/memory/minutes', { params: { year, month } })
}

/** 设置首席书记员 */
export function setSecretary(agentId: number | null) {
  return request.post<{ success: boolean; secretary_agent_id: number | null }>(
    '/hub/settings/secretary',
    { agent_id: agentId },
  )
}

/** 获取首席书记员 */
export function getSecretary() {
  return request.get<{ secretary_agent_id: number | null }>('/hub/settings/secretary')
}

/** 清空 War Room 日志 */
export function clearHubLogs() {
  return request.delete<{ success: boolean }>('/hub/logs')
}

/** 每日复盘一键导出 (返回 Markdown 纯文本) */
export async function getDailyRecap(date?: string): Promise<string> {
  // 直接用 axios 获取纯文本，绕过拦截器的 JSON 处理
  const { getAuthToken } = await import('@/utils/request')
  const token = getAuthToken()
  const params = date ? `?date=${date}` : ''
  const resp = await fetch(`/api/hub/daily-recap${params}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return await resp.text()
}

// ==================== Wake Conditions ====================

/** 唤醒条件 */
export interface WakeCondition {
  type: 'price_above' | 'price_below' | 'change_pct'
  symbol: string
  value: number
}

/** 唤醒条件响应 */
export interface WakeConditionsResponse {
  has_conditions: boolean
  conditions: WakeCondition[]
  display_text: string
  timeout_minutes: number
  remaining_minutes: number
  base_prices?: Record<string, number>
  created_at?: string
}

/** 查询 Agent 当前唤醒条件 */
export function getWakeConditions(agentId: number) {
  return request.get<WakeConditionsResponse>(`/hub/agents/${agentId}/wake-conditions`)
}
