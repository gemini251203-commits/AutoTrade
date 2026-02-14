/**
 * Task API
 * =========
 * 任务单相关 API
 * 
 * 端点对照表:
 *   GET  /task/              -> listTasks()
 *   POST /task/              -> createTask()
 *   POST /task/{id}/approve  -> approveTask()
 *   POST /task/{id}/reject   -> rejectTask()
 */

import request from '@/utils/request'

// ==================== Types ====================

/** 任务来源 */
export type TaskSource = 'user' | 'ai' | 'strategy' | 'grid'

/** 任务类型 */
export type TaskType = 'buy' | 'sell' | 'close' | 'adjust'

/** 任务状态 */
export type TaskStatus = 'pending' | 'approved' | 'rejected' | 'executing' | 'completed' | 'failed'

/** 任务响应 */
export interface TaskResponse {
  id: number
  source: TaskSource
  task_type: TaskType
  status: TaskStatus
  symbol: string
  side: string
  quantity: string  // Decimal 返回为字符串
  
  // 交易模式
  trading_mode: 'left_side' | 'right_side' | 'market' | null
  trade_side: 'long' | 'short' | null
  
  // 价格参数
  entry_low: string | null
  entry_high: string | null
  trigger_price: string | null
  max_deviation_pct: string | null
  confirm_interval: string | null
  timeout_hours: number | null
  expires_at: string | null
  
  // 🔥 两阶段条件参数
  condition_type: 'simple_breakout' | 'breakdown_reclaim' | 'breakout_pullback' | null
  condition_phase: number | null
  
  // 风控
  stop_loss: string | null
  take_profit: string | null
  leverage: number | null
  
  // AI 分析
  confidence: number | null
  note: string | null
  created_at: string | null
}

/** 任务创建请求 */
export interface TaskCreate {
  symbol: string
  task_type: TaskType
  side: string
  quantity: number | string
  
  // 交易模式
  trading_mode?: 'left_side' | 'right_side' | 'market'
  trade_side?: 'long' | 'short'
  
  // 价格参数
  entry_low?: number | string
  entry_high?: number | string
  trigger_price?: number | string
  
  // 右侧参数
  max_deviation_pct?: number | string
  confirm_interval?: string
  confirm_count?: number
  timeout_hours?: number
  
  // 🔥 两阶段条件类型
  condition_type?: 'simple_breakout' | 'breakdown_reclaim' | 'breakout_pullback'
  
  // 风控
  stop_loss?: number | string
  take_profit?: number | string
  leverage?: number
  note?: string
}

// ==================== API Functions ====================

/**
 * 获取任务列表
 * 
 * @param status 可选状态过滤
 * @param limit 限制数量
 * @returns 任务列表
 */
export async function listTasks(status?: TaskStatus, limit: number = 50): Promise<TaskResponse[]> {
  const params: Record<string, unknown> = { limit }
  if (status) {
    params.status_filter = status
  }
  const response = await request.get<TaskResponse[]>('/task/', { params })
  return response.data
}

/**
 * 创建任务
 * 
 * @param task 任务数据
 * @returns 创建的任务
 */
export async function createTask(task: TaskCreate): Promise<TaskResponse> {
  const response = await request.post<TaskResponse>('/task/', task)
  return response.data
}

/**
 * 审批任务 (触发自动执行)
 * 
 * @param taskId 任务 ID
 * @param autoExecute 是否自动执行 (默认 true)
 * @returns 更新后的任务
 */
export async function approveTask(taskId: number, autoExecute: boolean = true): Promise<TaskResponse> {
  const response = await request.post<TaskResponse>(`/task/${taskId}/approve`, null, {
    params: { auto_execute: autoExecute },
  })
  return response.data
}

/**
 * 拒绝任务
 * 
 * @param taskId 任务 ID
 * @returns 更新后的任务
 */
export async function rejectTask(taskId: number): Promise<TaskResponse> {
  const response = await request.post<TaskResponse>(`/task/${taskId}/reject`)
  return response.data
}

/**
 * 取消任务
 * 
 * @param taskId 任务 ID
 * @returns 更新后的任务
 */
export async function cancelTask(taskId: number): Promise<TaskResponse> {
  const response = await request.post<TaskResponse>(`/task/${taskId}/cancel`)
  return response.data
}
