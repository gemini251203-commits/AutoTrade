/**
 * Wallet Type Definitions
 * ========================
 * 
 * 🔒 数据契约: 这些类型定义必须严格匹配后端 Pydantic 模型
 * 
 * Backend Source:
 *   - backend/app/api/wallet.py → WalletBalanceResponse
 *   - backend/app/models/wallet.py → Wallet ORM Model
 */

// ==================================================
// API Response Types (后端返回的原始数据格式)
// ==================================================

/**
 * GET /api/wallet/balance 响应
 * 
 * ⚠️ 字段命名: 必须使用下划线 (snake_case)，与后端一致
 * ⚠️ 值类型: 后端 Decimal 序列化后可能是字符串
 */
export interface WalletAPIResponse {
  /** 可用余额 (可用来下单的资金) */
  available: string | number
  
  /** 冻结金额 (已下单锁定的资金) */
  frozen: string | number
  
  /** 总权益 = available + frozen (⚠️ 下划线!) */
  total_equity: string | number
  
  /** 总盈亏 (已实现盈亏累计) (⚠️ 下划线!) */
  total_pnl: string | number
}

/**
 * GET /api/wallet/ 响应
 */
export interface WalletResponse {
  /** 用户 ID */
  user_id: number
  
  /** 可用余额 */
  balance: string | number
  
  /** 冻结金额 */
  frozen: string | number
  
  /** 总盈亏 */
  total_pnl: string | number
}

// ==================================================
// Frontend Store State (前端状态 - camelCase)
// ==================================================

/**
 * Wallet Store State
 * 
 * 映射规则: API snake_case → Store camelCase
 *   - total_equity → totalEquity
 *   - total_pnl → totalPnl
 */
export interface WalletState {
  available: number
  frozen: number
  totalEquity: number
  totalPnl: number
  currency: string
  loading: boolean
  error: string | null
}
