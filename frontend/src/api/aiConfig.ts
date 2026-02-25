/**
 * AI Config API
 * ==============
 * 用户 AI 配置相关 API
 * 
 * 端点对照表:
 *   GET  /user/ai-config       -> getAIConfig()
 *   PUT  /user/ai-config       -> updateAIConfig()
 *   POST /user/ai-config/test  -> testAIConnection()
 */

import request from '@/utils/request'

// ==================== Types ====================

/** AI 提供商 */
export type AIProvider = 'ollama' | 'deepseek' | 'openai'

/** AI 配置响应 (从后端获取) */
export interface AIConfigResponse {
  provider: string
  api_base_url: string | null
  api_key_masked: string | null  // 脱敏后的 key
  api_model: string | null
  ollama_base_url: string | null
  ollama_model: string | null
  system_prompt: string | null
  use_deep_thinking: boolean  // 深度思考模式
  max_leverage: number
  max_position_percent: number
  max_loss_percent: number
}

/** AI 配置更新请求 (发送到后端) */
export interface AIConfigUpdate {
  provider: AIProvider
  api_base_url?: string
  api_key?: string  // 明文 key，后端加密存储
  api_model?: string
  ollama_base_url?: string
  ollama_model?: string
  system_prompt?: string
  use_deep_thinking?: boolean  // 深度思考模式
  max_leverage?: number
  max_position_percent?: number
  max_loss_percent?: number
}

/** 测试连接请求 */
export interface AIConfigTestRequest {
  provider: AIProvider
  api_base_url?: string
  api_key?: string
  api_model?: string
  ollama_base_url?: string
  ollama_model?: string
}

/** 测试连接响应 */
export interface AIConfigTestResponse {
  success: boolean
  message: string
  model_info?: {
    available_models?: string[]
  }
}

// ==================== API Functions ====================

/**
 * 获取当前用户的 AI 配置
 * 
 * @returns AI 配置 (API Key 已脱敏)
 */
export async function getAIConfig(): Promise<AIConfigResponse> {
  const response = await request.get<AIConfigResponse>('/user/ai-config')
  return response.data
}

/**
 * 更新用户 AI 配置
 * 
 * @param config 配置更新内容
 * @returns 更新后的配置
 */
export async function updateAIConfig(config: AIConfigUpdate): Promise<AIConfigResponse> {
  const response = await request.put<AIConfigResponse>('/user/ai-config', config)
  return response.data
}

/**
 * 测试 AI 连接
 * 
 * @param config 测试配置
 * @returns 测试结果
 */
export async function testAIConnection(config: AIConfigTestRequest): Promise<AIConfigTestResponse> {
  const response = await request.post<AIConfigTestResponse>('/user/ai-config/test', config)
  return response.data
}
