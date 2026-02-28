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
 *   POST   /hub/agents/{id}/chat           -> chatWithAgent() (SSE)
 *   POST   /hub/board/deliberate           -> boardDeliberate()
 */

import request from '@/utils/request'

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
  system_prompt: string
  temperature: number
  status: HubAgentStatus
  is_active: boolean
  last_run_at: string | null
  last_error: string | null
  total_runs: number
  total_trades: number
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

/** 获取 Hub 全局状态 */
export function getHubStatus() {
  return request.get<HubStatus>('/hub/status')
}

/** 董事会辩论 */
export function boardDeliberate(topic: string, symbol: string = 'BTCUSDT') {
  return request.post<BoardResult>('/hub/board/deliberate', { topic, symbol })
}

/** SSE 对话 (独裁者模式) */
export function chatWithAgent(agentId: number, message: string): EventSource {
  // SSE 需要特殊处理, 使用 fetch + ReadableStream
  const token = localStorage.getItem('token')
  const baseUrl = import.meta.env.VITE_API_BASE || ''
  
  const eventSource = new EventSource(
    `${baseUrl}/api/hub/agents/${agentId}/chat?token=${token}`
  )
  
  return eventSource
}

/**
 * 从 localStorage 获取 auth token (兼容多账户模式)
 * 与 request.ts 中 getAuthToken() 保持一致
 */
function getHubAuthToken(): string | null {
  try {
    const sessions = localStorage.getItem('auth_sessions')
    const activeIndex = localStorage.getItem('auth_active_index')
    if (sessions) {
      const parsed = JSON.parse(sessions)
      const index = activeIndex ? parseInt(activeIndex, 10) : 0
      const token = parsed[index]?.token
      if (token) return token
    }
    return localStorage.getItem('token')
  } catch {
    return null
  }
}

/**
 * SSE 对话 (fetch 方式, 支持 POST body)
 */
export async function* streamChatWithAgent(
  agentId: number,
  message: string
): AsyncGenerator<{ type: string; content?: string; tool?: string; args?: any; result?: string }> {
  const token = getHubAuthToken()
  const baseUrl = import.meta.env.VITE_API_BASE || ''
  
  const response = await fetch(`${baseUrl}/api/hub/agents/${agentId}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({ message }),
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
}
