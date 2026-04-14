/**
 * Common Types — 跨模块通用类型定义
 * =====================================
 * 
 * 统一的分页、响应包装、错误类型等，供所有模块复用。
 * 
 * 使用方式:
 *   import type { PaginatedRequest, ApiError } from '@/types'
 */

// ==================================================
// 分页 (Pagination)
// ==================================================

/** 分页请求参数 */
export interface PaginatedRequest {
  /** 页码 (1-based) */
  page?: number
  /** 每页条数 (默认 20) */
  limit?: number
  /** 偏移量 (可替代 page) */
  offset?: number
}

/** 分页响应包装 */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  limit: number
  has_more: boolean
}

// ==================================================
// API 响应 (Response Wrappers)
// ==================================================

/** 通用成功响应 */
export interface SuccessResponse {
  success: boolean
  message?: string
}

/** 通用删除响应 */
export interface DeleteResponse {
  message: string
}

// ==================================================
// API 错误 (Error)
// ==================================================

/** 后端错误响应 (FastAPI HTTPException) */
export interface ApiError {
  detail: string
  status_code?: number
}

/** 表单验证错误 (FastAPI ValidationError) */
export interface ValidationError {
  detail: Array<{
    loc: (string | number)[]
    msg: string
    type: string
  }>
}

// ==================================================
// 通用字段类型
// ==================================================

/** 后端 Decimal 序列化后的类型 (可能是 string 或 number) */
export type DecimalField = string | number

/** ISO 8601 日期时间字符串 */
export type ISODateString = string

/** 交易对符号 (如 "BTCUSDT") */
export type Symbol = string

/** 交易方向 */
export type TradeSide = 'long' | 'short'

/** 订单方向 */
export type OrderDirection = 'buy' | 'sell'
