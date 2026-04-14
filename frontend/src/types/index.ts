/**
 * Types Index — 统一类型重导出
 * ===============================
 * 
 * 汇集并重导出项目中所有类型定义，
 * 让组件可以从 '@/types' 一次性导入所需类型。
 * 
 * 使用方式:
 *   import type { HubAgent, OrderResponse, WalletState } from '@/types'
 * 
 * 设计原则:
 *   - 各 API 文件 (api/hub.ts 等) 仍是类型的 "源文件"
 *   - 本文件仅做重导出，不定义新类型
 *   - 避免双重维护
 */

// ===== 通用类型 =====
export type {
  PaginatedRequest,
  PaginatedResponse,
  SuccessResponse,
  DeleteResponse,
  ApiError,
  ValidationError,
  DecimalField,
  ISODateString,
  Symbol,
  TradeSide,
  OrderDirection,
} from './common'

// ===== Wallet =====
export type {
  WalletAPIResponse,
  WalletResponse,
  WalletState,
} from './wallet'

// ===== Hub =====
export type {
  ToolInfo,
  ToolListResponse,
  HubAgentStatus,
  HubAgent,
  HubAgentCreateRequest,
  HubAgentUpdateRequest,
  HubStatus,
  BoardOpinion,
  BoardConsensus,
  BoardResult,
  HubLogEntry,
  WakeCondition,
  WakeConditionsResponse,
} from '@/api/hub'

// ===== Order =====
export type {
  OrderStatus,
  TpSlPreviewRequest,
  TpSlPreviewResponse,
  LeverageInfoRequest,
  LeverageInfoResponse,
  OrderCreateRequest,
  OrderResponse,
} from '@/api/order'

// ===== Position =====
export type {
  PositionStatus,
  PositionSide,
  PositionResponse,
  PositionWithPnlResponse,
  ClosePositionResponse,
} from '@/api/position'

// ===== Grid =====
export type {
  GridType,
  GridDirection,
  GridStatus,
  GridCreateRequest,
  GridStartRequest,
  GridResponse,
  GridDetailResponse,
} from '@/api/grid'

// ===== Strategy =====
export type {
  StrategyStatus,
  StrategyRequest,
  StrategyResponse,
  StrategyLogResponse,
  StrategyTemplate,
  TradeMemoryResponse,
  StrategyStats,
} from '@/api/strategy'

// ===== Risk =====
export type {
  PositionRiskResponse,
  AccountRiskResponse,
  RiskCheckResponse,
} from '@/api/risk'

// ===== News =====
export type {
  NewsArticle,
  MarketSentiment,
  NewsAlert,
  NewsThinking,
  TradingStats,
  FearGreedIndex,
  CreateAlertParams,
  UpdateAlertParams,
} from '@/api/news'

// ===== Trend =====
export type {
  TrendSchemeResponse,
  TrendResultData,
  TrendSnapshotResponse,
} from '@/api/trend'

// ===== Task =====
export type {
  TaskSource,
  TaskType,
  TaskStatus,
  TaskResponse,
  TaskCreate,
} from '@/api/task'

// ===== AI Signal =====
export type {
  ParseSignalRequest,
  ParsedSignal,
  ParseSignalResponse,
  AIContextResponse,
  AnalyzeResponse,
} from '@/api/aiSignal'

// ===== Prompt =====
export type {
  MarketTag,
  PromptTemplate,
  PromptTemplateCreateRequest,
  PromptTemplateUpdateRequest,
  TemplatePerformance,
} from '@/api/prompt'
