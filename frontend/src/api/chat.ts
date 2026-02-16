/**
 * Agent API
 * ==========
 * AI 交易代理对话 API
 * 
 * 端点对照表:
 *   GET    /agent/personas                    -> getPersonas()
 *   POST   /agent/conversations               -> createConversation()
 *   GET    /agent/conversations               -> listConversations()
 *   DELETE /agent/conversations/{id}          -> deleteConversation()
 *   POST   /agent/conversations/{id}/chat     -> sendMessage() (SSE)
 *   GET    /agent/conversations/{id}/messages -> getMessages()
 */

import request from '@/utils/request'

// ==================== Types ====================

/** AI 角色 */
export interface Persona {
  id: string
  name: string
}

/** 对话会话 */
export interface Conversation {
  id: number
  title: string
  persona: string
  created_at: string
  updated_at: string
}

/** 聊天消息 */
export interface ChatMessage {
  id: number
  role: string
  content: string
  tool_name: string | null
  tool_result: string | null
  created_at: string
}

/** SSE 事件 */
export interface SSEEvent {
  type: 'text' | 'tool_call' | 'tool_result' | 'done' | 'error'
  content?: string
  tool?: string
  args?: Record<string, unknown>
  result?: string
  full_reply?: string
  message?: string
}

// ==================== API Functions ====================

/** 获取可用 AI 角色列表 */
export async function getPersonas(): Promise<Persona[]> {
  const response = await request.get<Persona[]>('/agent/personas')
  return response.data
}

/** 创建新会话 */
export async function createConversation(persona: string = 'conservative'): Promise<Conversation> {
  const response = await request.post<Conversation>('/agent/conversations', { persona })
  return response.data
}

/** 获取会话列表 */
export async function listConversations(): Promise<Conversation[]> {
  const response = await request.get<Conversation[]>('/agent/conversations')
  return response.data
}

/** 删除会话 */
export async function deleteConversation(id: number): Promise<{ message: string }> {
  const response = await request.delete<{ message: string }>(`/agent/conversations/${id}`)
  return response.data
}

/** 获取会话历史消息 */
export async function getMessages(conversationId: number, limit: number = 50): Promise<ChatMessage[]> {
  const response = await request.get<ChatMessage[]>(`/agent/conversations/${conversationId}/messages`, {
    params: { limit },
  })
  return response.data
}

/**
 * 发送消息 (SSE 流式)
 * 
 * 注意: 这里不使用 request (Axios) 而是直接使用 fetch + EventSource
 * 因为 Axios 不原生支持 SSE 流式响应
 */
export function sendMessage(
  conversationId: number,
  message: string,
  token: string,
  onEvent: (event: SSEEvent) => void,
  onError?: (error: Error) => void,
): AbortController {
  const controller = new AbortController()

  const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
  const url = `${baseUrl}/api/agent/conversations/${conversationId}/chat`

  fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({ message }),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 解析 SSE 数据行
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // 保留不完整的行

        for (const line of lines) {
          const trimmed = line.trim()
          if (trimmed.startsWith('data: ')) {
            try {
              const data = JSON.parse(trimmed.slice(6)) as SSEEvent
              onEvent(data)
            } catch {
              // 忽略解析失败的行
            }
          }
        }
      }
    })
    .catch((error) => {
      if (error.name !== 'AbortError') {
        onError?.(error)
      }
    })

  return controller
}

// ==================== Autopilot ====================

/** Autopilot 状态 */
export interface AutopilotStatus {
  running: boolean
  symbols: string[]
  interval: string
}

/** Autopilot 启动配置 */
export interface AutopilotConfig {
  symbols: string[]
  interval: string
}

/** 启动 autopilot */
export async function startAutopilot(config: AutopilotConfig) {
  const response = await request.post('/agent/autopilot/start', config)
  return response.data
}

/** 停止 autopilot */
export async function stopAutopilot() {
  const response = await request.post('/agent/autopilot/stop')
  return response.data
}

/** 手动触发一次 autopilot 决策 */
export async function runOnceAutopilot(symbol: string = 'BTCUSDT') {
  const response = await request.post('/agent/autopilot/run-once', null, {
    params: { symbol },
  })
  return response.data
}

/** 获取 autopilot 状态 */
export async function getAutopilotStatus(): Promise<AutopilotStatus> {
  const response = await request.get<AutopilotStatus>('/agent/autopilot/status')
  return response.data
}
