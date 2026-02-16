<script setup lang="ts">
/**
 * AI Signal Assistant
 * ====================
 * AI 信号助手页面
 * 
 * 功能:
 * 1. 输入喊单文本
 * 2. AI 解析为结构化任务
 * 3. 用户确认/修改后执行
 */

import { ref, computed, onMounted } from 'vue'
import MainLayout from '@/layouts/MainLayout.vue'
import {
  NCard,
  NInput,
  NButton,
  NSpace,
  NGrid,
  NGi,
  NStatistic,
  NTag,
  NProgress,
  NText,
  NIcon,
  NAlert,
  NDescriptions,
  NDescriptionsItem,
  NInputNumber,
  NModal,
  NSpin,
  NEmpty,
  NDivider,
  NFormItem,
  NSelect,
  createDiscreteApi,
  NAvatar,
} from 'naive-ui'
import { 
  Send, 
  CheckmarkCircle, 
  CloseCircle, 
  Refresh, 
  WalletOutline, 
  TrendingUp, 
  AlertCircle,
  FlashOutline,
  PulseOutline,
  AnalyticsOutline,
} from '@vicons/ionicons5'
import { useRouter } from 'vue-router'
import { parseSignal, getAIContext, type ParsedSignal, type AIContextResponse } from '@/api/aiSignal'
import { createTask, approveTask, rejectTask, cancelTask, listTasks, type TaskResponse } from '@/api/task'
import { previewTpSl, type TpSlPreviewResponse } from '@/api/order'
import request from '@/utils/request'
import { useSymbolStore } from '@/stores/symbol'

const router = useRouter()
const { message } = createDiscreteApi(['message'])
const symbolStore = useSymbolStore()

// ==================== State ====================

const inputText = ref('')
const loading = ref(false)
const contextLoading = ref(false)
const parsedSignal = ref<ParsedSignal | null>(null)
const context = ref<AIContextResponse | null>(null)
const pendingTasks = ref<TaskResponse[]>([])
const showEditModal = ref(false)

// 编辑中的信号
const editingSignal = ref<ParsedSignal | null>(null)

// 交易模式: 'normal' 普通交易 | 'grid' 网格交易
const tradeMode = ref<'normal' | 'grid'>('normal')

// 止盈止损预览
const tpSlPreview = ref<TpSlPreviewResponse | null>(null)

// 快捷示例
const examples = [
  'BTC多 入场78000-78500 止损77000 止盈82000 5倍杠杆',
  'ETH 做空 当前价 止损+3% 止盈-10% 投入500U',
  'SOL 网格 50-80 20格 等差 做多 500U',
]

// ==================== Computed ====================

const confidenceType = computed(() => {
  if (!parsedSignal.value) return 'default'
  const conf = parsedSignal.value.confidence
  if (conf >= 0.8) return 'success'
  if (conf >= 0.5) return 'warning'
  return 'error'
})

const sideColor = computed(() => {
  if (!parsedSignal.value) return '#fff'
  return parsedSignal.value.side === 'long' ? '#00c853' : '#ff4757'
})

// 新增: 预计止损盈亏
const estimatedStopLossProfit = computed(() => {
  const signal = editingSignal.value
  if (!signal || !signal.stop_loss) return null
  
  const entryPrice = signal.entry_price || signal.entry_low || 0
  const margin = signal.margin || 0
  const leverage = signal.leverage || 1
  const isLong = signal.side === 'long'
  
  if (entryPrice <= 0 || margin <= 0) return null
  
  // 合约数量 = (保证金 × 杠杆) / 入场价格
  const contractQty = (margin * leverage) / entryPrice
  
  // 盈亏 = 合约数量 × (止损价 - 入场价)  (做多)
  // 盈亏 = 合约数量 × (入场价 - 止损价)  (做空)
  let pnl = isLong 
    ? contractQty * (signal.stop_loss - entryPrice)
    : contractQty * (entryPrice - signal.stop_loss)
  
  return pnl
})

// 新增: 预计止盈盈亏
const estimatedTakeProfitProfit = computed(() => {
  const signal = editingSignal.value
  if (!signal || !signal.take_profit) return null
  
  const entryPrice = signal.entry_price || signal.entry_low || 0
  const margin = signal.margin || 0
  const leverage = signal.leverage || 1
  const isLong = signal.side === 'long'
  
  if (entryPrice <= 0 || margin <= 0) return null
  
  // 合约数量 = (保证金 × 杠杆) / 入场价格
  const contractQty = (margin * leverage) / entryPrice
  
  // 盈亏 = 合约数量 × (止盈价 - 入场价)  (做多)
  // 盈亏 = 合约数量 × (入场价 - 止盈价)  (做空)
  let pnl = isLong 
    ? contractQty * (signal.take_profit - entryPrice)
    : contractQty * (entryPrice - signal.take_profit)
  
  return pnl
})

// ==================== Methods ====================

async function loadContext() {
  contextLoading.value = true
  try {
    // 使用 store 的当前交易对获取上下文
    context.value = await getAIContext(symbolStore.currentSymbol)
  } catch (error) {
    console.error('Failed to load context:', error)
  } finally {
    contextLoading.value = false
  }
}

async function loadPendingTasks() {
  try {
    pendingTasks.value = await listTasks('pending', 10)
  } catch (error) {
    console.error('Failed to load tasks:', error)
  }
}

// 获取止盈止损盈亏预览
async function fetchTpSlPreviewForSignal(signal: ParsedSignal) {
  if (!signal.stop_loss && !signal.take_profit) {
    tpSlPreview.value = null
    return
  }
  
  // 计算入场价和数量
  const entryPrice = signal.entry_price || signal.entry_low || signal.entry_high || 0
  const qty = signal.margin && entryPrice > 0 
    ? (signal.margin * signal.leverage) / entryPrice 
    : 0.001  // 默认数量
  
  if (entryPrice <= 0) {
    tpSlPreview.value = null
    return
  }
  
  try {
    const result = await previewTpSl({
      symbol: signal.symbol,
      side: signal.side,
      quantity: qty.toFixed(5),
      entry_price: entryPrice.toString(),
      take_profit: signal.take_profit ? signal.take_profit.toString() : undefined,
      stop_loss: signal.stop_loss ? signal.stop_loss.toString() : undefined,
      leverage: signal.leverage,
    })
    
    tpSlPreview.value = result
  } catch (e) {
    console.error('[SignalAssistant] TP/SL 预览失败:', e)
    tpSlPreview.value = null
  }
}

async function handleParse() {
  if (!inputText.value.trim()) {
    message.warning('请输入喊单内容')
    return
  }
  
  loading.value = true
  parsedSignal.value = null
  tpSlPreview.value = null
  
  try {
    const result = await parseSignal(inputText.value.trim())
    
    if (result.success && result.signal) {
      parsedSignal.value = result.signal
      
      // 自动切换交易模式: 如果 AI 检测到网格交易
      if (result.signal.is_grid) {
        tradeMode.value = 'grid'
      } else {
        tradeMode.value = 'normal'
        
        // 获取止盈止损预览
        await fetchTpSlPreviewForSignal(result.signal)
      }
      
      message.success('解析成功')
    } else {
      message.error(result.error || '解析失败')
    }
  } catch (error) {
    console.error('Parse failed:', error)
    message.error('解析失败，请检查 AI 配置')
  } finally {
    loading.value = false
  }
}

async function handleConfirm() {
  if (!parsedSignal.value) return
  
  loading.value = true
  
  try {
    // 根据交易模式选择不同的执行路径
    if (tradeMode.value === 'grid') {
      // ========== 网格交易模式 ==========
      const gridParams = {
        name: `${parsedSignal.value.symbol} 网格 #${Date.now() % 10000}`,
        symbol: parsedSignal.value.symbol,
        lower_price: parsedSignal.value.grid_lower || parsedSignal.value.entry_low || 0,
        upper_price: parsedSignal.value.grid_upper || parsedSignal.value.entry_high || 0,
        grid_count: parsedSignal.value.grid_count || 10,
        investment: parsedSignal.value.grid_investment || parsedSignal.value.margin || 100,
        leverage: parsedSignal.value.leverage || 5,
        grid_type: parsedSignal.value.grid_type || 'arithmetic',
        direction: parsedSignal.value.grid_direction || 'neutral',
        stop_loss_price: parsedSignal.value.stop_loss || null,
        take_profit_price: parsedSignal.value.take_profit || null,
      }
      
      // 1. 创建网格机器人
      const createResp = await request.post('/grid/', gridParams)
      const botId = createResp.data.id
      
      // 2. 获取当前价格并启动网格
      const tickerResp = await request.get(`/market/ticker/${parsedSignal.value.symbol}`)
      const currentPrice = tickerResp.data?.price || 0
      
      if (currentPrice > 0) {
        await request.post(`/grid/${botId}/start`, { current_price: currentPrice })
        message.success('网格机器人已创建并启动!')
      } else {
        message.success('网格机器人已创建 (请手动启动)')
      }
      
    } else {
      // ========== 普通交易模式 (Market / Left / Right) ==========
      const taskType = parsedSignal.value.side === 'long' ? 'buy' : 'sell'
      
      // 确定交易模式
      let tradingMode = 'market'
      if (parsedSignal.value.trading_mode) {
        tradingMode = parsedSignal.value.trading_mode
      } else if (parsedSignal.value.trade_style === 'left_side') {
        tradingMode = 'left_side'
      } else if (parsedSignal.value.trade_style === 'right_side') {
        tradingMode = 'right_side'
      }
      
      const task = await createTask({
        symbol: parsedSignal.value.symbol,
        task_type: taskType as any,
        side: parsedSignal.value.side,
        quantity: parsedSignal.value.margin || 100,
        
        // 交易模式参数
        trading_mode: tradingMode as any,
        trade_side: parsedSignal.value.side as any,
        
        // 价格参数
        entry_low: parsedSignal.value.entry_low || parsedSignal.value.entry_price || undefined,
        entry_high: parsedSignal.value.entry_high || undefined,
        trigger_price: parsedSignal.value.trigger_price || undefined,
        
        // 右侧参数
        max_deviation_pct: parsedSignal.value.max_deviation_pct || 0.5,
        confirm_interval: parsedSignal.value.confirm_interval || '15m',
        timeout_hours: parsedSignal.value.timeout_hours || 24,
        
        // 风控
        stop_loss: parsedSignal.value.stop_loss || undefined,
        take_profit: parsedSignal.value.take_profit || undefined,
        leverage: parsedSignal.value.leverage || 5,
        
        note: `AI解析 [${tradingMode}] | 置信度: ${(parsedSignal.value.confidence * 100).toFixed(0)}%`,
      })
      
      // 自动审批执行 (Monitor or Execute)
      await approveTask(task.id, true)
      
      if (tradingMode === 'right_side') {
        message.success('已创建条件单并开始监控')
      } else if (tradingMode === 'left_side') {
        message.success('已创建限价挂单')
      } else {
        message.success('市价任务已执行')
      }
    }
    
    // 清理状态
    parsedSignal.value = null
    inputText.value = ''
    tradeMode.value = 'normal'
    
    // 刷新上下文
    loadContext()
    loadPendingTasks()
    
  } catch (error: any) {
    console.error('Confirm failed:', error)
    const detail = error.response?.data?.detail || '执行失败'
    message.error(detail)
  } finally {
    loading.value = false
  }
}

function handleEdit() {
  if (!parsedSignal.value) return
  editingSignal.value = { ...parsedSignal.value }
  showEditModal.value = true
}

function handleEditSave() {
  if (editingSignal.value) {
    parsedSignal.value = { ...editingSignal.value }
    showEditModal.value = false
    message.success('参数已更新')
  }
}

function handleCancel() {
  parsedSignal.value = null
  inputText.value = ''
}

function handleExample(text: string) {
  inputText.value = text
}

async function handleCancelTask(taskId: number) {
  try {
    await cancelTask(taskId)
    message.success('任务已取消')
    loadPendingTasks() // 刷新列表
  } catch (error) {
    console.error('Cancel failed:', error)
    message.error('取消失败')
  }
}

// Removed goBack - MainLayout handles navigation

function formatPrice(price: number | null): string {
  if (price === null || price === undefined) return '-'
  return price.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

// ==================== Lifecycle ====================

onMounted(() => {
  loadContext()
  loadPendingTasks()
})
</script>

<template>
  <MainLayout>
  <div class="signal-page">
    <div class="bg-glow"></div>
    
    <!-- Header -->
    <div class="page-header">
      <div class="title-section">
        <h1 class="page-title">AI 信号助手</h1>
        <NTag size="small" type="primary" round class="ml-2">Command Center</NTag>
      </div>
      <NButton secondary circle type="primary" @click="loadContext" class="refresh-btn">
        <template #icon>
          <NIcon :component="Refresh" />
        </template>
      </NButton>
    </div>

    <div class="main-layout">
      <NGrid :cols="24" :x-gap="24" :y-gap="24">
        <!-- 左侧: 账户与状态 -->
        <NGi :span="6">
          <div class="sidebar-col">
            <!-- 账户卡片 -->
            <NCard class="dashboard-card wallet-card" :bordered="false">
              <div class="card-icon-bg success">
                <NIcon :component="WalletOutline" />
              </div>
              <NSpin :show="contextLoading">
                 <div class="market-header">
                  <span class="label">账户概览</span>
                </div>
                <div class="wallet-content" v-if="context?.wallet">
                  <div class="balance-row">
                    <span class="sub-label">可用余额</span>
                    <span class="val">${{ Math.floor(context.wallet.available).toLocaleString() }}</span>
                  </div>
                  <NDivider style="margin: 8px 0" />
                  <div class="balance-row">
                    <span class="sub-label">总权益</span>
                    <span class="val highlight">${{ Math.floor(context.wallet.equity).toLocaleString() }}</span>
                  </div>
                </div>
              </NSpin>
            </NCard>

            <!-- 状态统计 -->
            <NCard class="dashboard-card status-card" :bordered="false">
              <div class="status-grid">
                <div class="stat-item">
                  <span class="num">{{ context?.positions?.length || 0 }}</span>
                  <span class="txt">持仓</span>
                </div>
                <div class="stat-item">
                  <span class="num">{{ context?.pending_orders || 0 }}</span>
                  <span class="txt">挂单</span>
                </div>
                <div class="stat-item">
                  <span class="num">{{ context?.running_grids || 0 }}</span>
                  <span class="txt">网格</span>
                </div>
              </div>
            </NCard>
          </div>
        </NGi>

        <!-- 中间: AI 指令终端 -->
        <NGi :span="12">
          <div class="center-col">
            <!-- 输入终端 -->
            <NCard class="terminal-card" :bordered="false" title="指令终端">
              <template #header-extra>
                <NIcon :component="FlashOutline" color="#eab308" />
              </template>
              
              <div class="terminal-input-wrapper">
                <NInput
                  v-model:value="inputText"
                  type="textarea"
                  :rows="5"
                  placeholder="// 输入交易指令..."
                  :disabled="loading"
                  class="terminal-input"
                  :bordered="false"
                />
                <div class="terminal-footer">
                   <NButton
                    type="primary"
                    :loading="loading"
                    :disabled="!inputText.trim()"
                    @click="handleParse"
                    class="analyze-btn"
                    color="#8a2be2"
                  >
                    <template #icon>
                      <NIcon :component="AnalyticsOutline" />
                    </template>
                    解析指令 / ANALYZE
                  </NButton>
                </div>
              </div>

              <div class="quick-examples">
                <NTag 
                  v-for="(ex, i) in examples" 
                  :key="i"
                  check
                  clickable 
                  @click="handleExample(ex)"
                  class="example-tag"
                  :bordered="false"
                >
                  {{ ex.substring(0, 15) }}...
                </NTag>
              </div>
            </NCard>

            <!-- 解析结果 (动态展示) -->
            <transition name="fade-slide">
              <NCard v-if="parsedSignal" class="result-card" :bordered="false">
                 <div class="result-glow"></div>
                 
                 <!-- Header -->
                 <div class="result-header">
                    <!-- 币种标签 (AI 检测到的交易对) -->
                    <div class="symbol-badge">
                      <NAvatar 
                        :size="24" 
                        round 
                        :style="{ background: 'linear-gradient(135deg, #f7931a 0%, #ffbe3d 100%)' }"
                      >
                        {{ parsedSignal.symbol?.replace('USDT', '').charAt(0) || 'B' }}
                      </NAvatar>
                      <span class="symbol-name">{{ parsedSignal.symbol || 'BTCUSDT' }}</span>
                    </div>
                    <div class="signal-badge" :class="parsedSignal.side">
                      {{ parsedSignal.side === 'long' ? 'LONG / 做多' : 'SHORT / 做空' }}
                    </div>
                    <div class="confidence-meter">
                       <span class="label">置信度</span>
                       <NProgress
                          type="line"
                          :percentage="parsedSignal.confidence * 100"
                          :status="confidenceType"
                          :height="8"
                          style="width: 100px"
                          processing
                       />
                       <span class="val">{{ (parsedSignal.confidence * 100).toFixed(0) }}%</span>
                    </div>
                 </div>

                 <!-- 交易模式切换 -->
                 <div class="trade-mode-tabs">
                    <button 
                      :class="['mode-tab', tradeMode === 'normal' ? 'active' : '']"
                      @click="tradeMode = 'normal'"
                    >
                      普通交易
                    </button>
                    <button 
                      :class="['mode-tab', tradeMode === 'grid' ? 'active' : '']"
                      @click="tradeMode = 'grid'"
                    >
                      网格交易
                    </button>
                 </div>

                 <!-- ========== 普通交易模式 ========== -->
                 <template v-if="tradeMode === 'normal'">
                   <div class="signal-data-grid">
                      
                      <!-- 左侧挂单 -->
                      <template v-if="parsedSignal.trading_mode === 'left_side' || parsedSignal.trade_style === 'left_side'">
                        <div class="data-block entry">
                           <span class="label">挂单价格 (Entry)</span>
                           <span class="value text-primary">${{ formatPrice(parsedSignal.entry_price || parsedSignal.entry_low) }}</span>
                        </div>
                      </template>
                      
                      <!-- 右侧突破 -->
                      <template v-else-if="parsedSignal.trading_mode === 'right_side' || parsedSignal.trade_style === 'right_side'">
                        <div class="data-block entry">
                           <span class="label">突破触发 (Trigger)</span>
                           <span class="value text-purple">${{ formatPrice(parsedSignal.trigger_price) }}</span>
                        </div>
                      </template>
                      
                      <!-- 市价交易 -->
                      <template v-else>
                        <div class="data-block entry">
                           <span class="label">入场区间 (Entry)</span>
                           <span class="value">${{ formatPrice(parsedSignal.entry_low) }} - {{ formatPrice(parsedSignal.entry_high) }}</span>
                        </div>
                      </template>

                      <div class="data-block target">
                         <span class="label">目标止盈 (Target)</span>
                         <span class="value text-success">${{ formatPrice(parsedSignal.take_profit) }}</span>
                         <span v-if="tpSlPreview && tpSlPreview.take_profit_pnl !== 0" class="preview-badge profit">
                           +{{ tpSlPreview.take_profit_pnl.toFixed(2) }} USDT ({{ tpSlPreview.take_profit_pct.toFixed(1) }}%)
                         </span>
                      </div>
                      <div class="data-block stop">
                         <span class="label">止损价格 (Stop)</span>
                         <span class="value text-error">${{ formatPrice(parsedSignal.stop_loss) }}</span>
                         <span v-if="tpSlPreview && tpSlPreview.stop_loss_pnl !== 0" class="preview-badge loss">
                           {{ tpSlPreview.stop_loss_pnl.toFixed(2) }} USDT ({{ tpSlPreview.stop_loss_pct.toFixed(1) }}%)
                         </span>
                      </div>
                      
                      <!-- 风险回报比 -->
                      <div v-if="tpSlPreview && tpSlPreview.risk_reward_ratio > 0" class="data-block ratio">
                         <span class="label">风险回报比</span>
                         <span class="value text-warning">1 : {{ tpSlPreview.risk_reward_ratio.toFixed(2) }}</span>
                      </div>
                   </div>
                   
                   <div class="signal-meta-grid">
                      <div class="meta-item">
                        <span class="label">模式</span>
                        <span class="val">
                            {{ 
                                (parsedSignal.trading_mode === 'left_side' || parsedSignal.trade_style === 'left_side') ? '左侧挂单' : 
                                (parsedSignal.trading_mode === 'right_side' || parsedSignal.trade_style === 'right_side') ? '右侧突破' : '市价成交' 
                            }}
                        </span>
                      </div>
                      <div class="meta-item">
                        <span class="label">杠杆</span>
                        <span class="val">{{ parsedSignal.leverage }}x</span>
                      </div>
                      <div class="meta-item">
                        <span class="label">保证金</span>
                        <span class="val">${{ formatPrice(parsedSignal.margin) }}</span>
                      </div>
                      
                      <!-- 右侧额外信息 -->
                      <div class="meta-item" v-if="parsedSignal.trading_mode === 'right_side'">
                        <span class="label">确认</span>
                        <span class="val">{{ parsedSignal.confirm_interval || '15m' }}</span>
                      </div>
                   </div>
                 </template>

                 <!-- ========== 网格交易模式 ========== -->
                 <template v-else>
                   <div class="signal-data-grid grid-mode">
                      <div class="data-block entry">
                         <span class="label">网格下限 (Lower)</span>
                         <span class="value">${{ formatPrice(parsedSignal.grid_lower || parsedSignal.entry_low) }}</span>
                      </div>
                      <div class="data-block target">
                         <span class="label">网格上限 (Upper)</span>
                         <span class="value">${{ formatPrice(parsedSignal.grid_upper || parsedSignal.entry_high) }}</span>
                      </div>
                      <div class="data-block stop">
                         <span class="label">止损价格 (Stop)</span>
                         <span class="value text-error">${{ formatPrice(parsedSignal.stop_loss) }}</span>
                      </div>
                   </div>
                   
                   <div class="signal-meta-grid grid-mode">
                      <div class="meta-item">
                        <span class="label">网格数量</span>
                        <span class="val">{{ parsedSignal.grid_count || 10 }} 格</span>
                      </div>
                      <div class="meta-item">
                        <span class="label">杠杆</span>
                        <span class="val">{{ parsedSignal.leverage }}x</span>
                      </div>
                      <div class="meta-item">
                        <span class="label">投资额</span>
                        <span class="val">${{ formatPrice(parsedSignal.grid_investment || parsedSignal.margin) }}</span>
                      </div>
                      <div class="meta-item">
                        <span class="label">类型</span>
                        <span class="val">{{ parsedSignal.grid_type === 'geometric' ? '等比' : '等差' }}</span>
                      </div>
                      <div class="meta-item">
                        <span class="label">方向</span>
                        <span class="val">{{ parsedSignal.grid_direction === 'neutral' ? '双向' : (parsedSignal.grid_direction === 'long' ? '做多' : '做空') }}</span>
                      </div>
                   </div>
                 </template>
                 
                 <NDivider />
                 
                 <!-- AI Analysis -->
                 <div class="ai-reasoning" v-if="parsedSignal.reasoning">
                    <div class="reasoning-title">
                       <NIcon :component="AnalyticsOutline" />
                       AI 策略分析
                    </div>
                    <p class="reasoning-text">{{ parsedSignal.reasoning }}</p>
                 </div>

                 <!-- Warnings -->
                 <div class="warnings-box" v-if="parsedSignal.warnings?.length">
                    <div class="warning-item" v-for="(w, i) in parsedSignal.warnings" :key="i">
                       <NIcon :component="AlertCircle" color="#f59e0b" />
                       {{ w }}
                    </div>
                 </div>

                 <!-- Actions -->
                 <div class="action-bar">
                    <NButton secondary @click="handleCancel" class="action-btn">
                       <template #icon><NIcon :component="CloseCircle" /></template>
                       忽略
                    </NButton>
                    <NButton secondary type="warning" @click="handleEdit" class="action-btn">
                       调整参数
                    </NButton>
                    <NButton type="primary" color="#00c853" @click="handleConfirm" class="action-btn confirm" :loading="loading">
                       <template #icon><NIcon :component="CheckmarkCircle" /></template>
                       执行信号
                    </NButton>
                 </div>
              </NCard>
            </transition>
          </div>
        </NGi>

        <!-- 右侧: 任务队列 -->
        <NGi :span="6">
          <NCard class="dashboard-card tasks-panel" title="任务队列" :bordered="false">
             <template v-if="pendingTasks.length">
                <div class="task-list">
                  <div 
                    v-for="task in pendingTasks" 
                    :key="task.id"
                    class="task-row"
                  >
                    <div class="task-icon" :class="task.side">
                      <NIcon :component="task.side === 'long' ? TrendingUp : FlashOutline" />
                    </div>
                    <div class="task-info">
                       <div class="task-top">
                          <span class="symbol">{{ task.symbol }}</span>
                          <span class="side" :class="task.side">{{ task.side.toUpperCase() }}</span>
                       </div>
                       <div class="task-btm">
                          {{ task.task_type }} • {{ task.quantity }} U
                       </div>
                    </div>
                    <div class="task-status">
                       <template v-if="['pending', 'executing', 'monitoring'].includes(task.status)">
                          <NButton size="tiny" type="error" ghost @click="handleCancelTask(task.id)">
                             取消
                          </NButton>
                       </template>
                       <template v-else>
                          <NTag :type="task.status === 'completed' ? 'success' : 'default'" size="small">
                             {{ task.status }}
                          </NTag>
                       </template>
                    </div>
                  </div>
                </div>
             </template>
             <div v-else class="empty-state">
                <NIcon :component="PulseOutline" size="40" depth="3" />
                <span>无待处理任务</span>
             </div>
          </NCard>
        </NGi>
      </NGrid>
    </div>

    <!-- 高级编辑弹窗 -->
    <NModal 
       v-model:show="showEditModal" 
       class="premium-modal"
       :mask-closable="false"
    >
      <NCard 
        style="width: 600px" 
        :bordered="false" 
        size="huge" 
        role="dialog" 
        aria-modal="true"
        class="modal-card"
      >
         <template #header>
            <div class="modal-header">
               <NIcon :component="WalletOutline" color="#8a2be2" />
               参数修正
            </div>
         </template>
         
         <template v-if="editingSignal">
            <div class="modal-content-grid">
               <!-- 模式切换标签 -->
               <div class="modal-mode-tabs">
                  <button 
                    :class="['modal-mode-tab', tradeMode === 'normal' ? 'active' : '']"
                    @click="tradeMode = 'normal'"
                  >
                    普通交易参数
                  </button>
                  <button 
                    :class="['modal-mode-tab', tradeMode === 'grid' ? 'active' : '']"
                    @click="tradeMode = 'grid'"
                  >
                    网格交易参数
                  </button>
               </div>

               <!-- ========== 普通交易模式 ========== -->
               <template v-if="tradeMode === 'normal'">
                 
                 <!-- 交易模式选择 -->
                 <div class="section-title">交易模式</div>
                 <NGrid :cols="1" class="mb-4">
                    <NGi>
                       <NSelect 
                          v-model:value="editingSignal.trading_mode"
                          :options="[
                             { label: '市价立即成交 (Market)', value: 'market' },
                             { label: '左侧限价挂单 (Left Side)', value: 'left_side' },
                             { label: '右侧突破追单 (Right Side)', value: 'right_side' }
                          ]"
                          placeholder="选择交易模式"
                       />
                    </NGi>
                 </NGrid>

                 <!-- 右侧交易参数 -->
                 <template v-if="editingSignal.trading_mode === 'right_side'">
                    <div class="section-title">突破条件设置</div>
                    
                    <!-- 条件类型选择 -->
                    <NGrid :cols="1" class="mb-4">
                       <NGi>
                          <NFormItem label="条件类型">
                             <NSelect 
                                v-model:value="editingSignal.condition_type"
                                :options="[
                                   { label: '简单突破 (价格突破即入场)', value: 'simple_breakout' },
                                   { label: '跌破回抽 (做多: 跌破后回抽入场)', value: 'breakdown_reclaim' },
                                   { label: '突破回撤 (做空: 突破后回撤入场)', value: 'breakout_pullback' }
                                ]"
                                placeholder="选择条件类型"
                             />
                          </NFormItem>
                       </NGi>
                    </NGrid>
                    
                    <NGrid :cols="2" :x-gap="16">
                       <NGi>
                          <NFormItem label="触发价格 (Trigger Price)">
                             <NInputNumber v-model:value="editingSignal.trigger_price" :show-button="false">
                                <template #prefix>$</template>
                             </NInputNumber>
                          </NFormItem>
                       </NGi>
                       <NGi>
                          <NFormItem label="确认周期 (K线)">
                             <NSelect 
                                v-model:value="editingSignal.confirm_interval"
                                :options="[
                                   { label: '1分钟', value: '1m' },
                                   { label: '5分钟', value: '5m' },
                                   { label: '15分钟', value: '15m' },
                                   { label: '1小时', value: '1h' }
                                ]" 
                             />
                          </NFormItem>
                       </NGi>
                       <NGi>
                          <NFormItem label="最大偏离 (%)">
                             <NInputNumber v-model:value="editingSignal.max_deviation_pct" :step="0.1" :min="0.1" :max="5">
                                <template #suffix>%</template>
                             </NInputNumber>
                          </NFormItem>
                       </NGi>
                       <NGi>
                          <NFormItem label="超时时间 (小时)">
                             <NInputNumber v-model:value="editingSignal.timeout_hours" :step="1" :min="1" :max="168">
                                <template #suffix>H</template>
                             </NInputNumber>
                          </NFormItem>
                       </NGi>
                    </NGrid>
                 </template>

                 <!-- 左侧交易参数 -->
                 <template v-if="editingSignal.trading_mode === 'left_side'">
                    <div class="section-title">挂单设置</div>
                    <NGrid :cols="1" class="mb-4">
                       <NGi>
                          <NFormItem label="挂单价格 (Entry Price)">
                             <NInputNumber v-model:value="editingSignal.entry_price" :show-button="false">
                                <template #prefix>$</template>
                             </NInputNumber>
                          </NFormItem>
                       </NGi>
                    </NGrid>
                 </template>
                 
                 <!-- 价格参考 (Entry Low/High) -->
                 <div class="section-title" v-if="editingSignal.trading_mode === 'market'">参考区间</div>
                 <NGrid :cols="2" :x-gap="16" v-if="editingSignal.trading_mode === 'market'">
                    <NGi>
                       <NFormItem label="入场区间 (Low)">
                          <NInputNumber v-model:value="editingSignal.entry_low" :show-button="false">
                             <template #prefix>$</template>
                          </NInputNumber>
                       </NFormItem>
                    </NGi>
                    <NGi>
                       <NFormItem label="入场区间 (High)">
                          <NInputNumber v-model:value="editingSignal.entry_high" :show-button="false">
                             <template #prefix>$</template>
                          </NInputNumber>
                       </NFormItem>
                    </NGi>
                 </NGrid>

                 <!-- 止盈止损 -->
                 <div class="section-title mt-4">风控参数</div>
                 <NGrid :cols="2" :x-gap="16">
                    <NGi>
                       <NFormItem label="止损价格 (Stop Loss)">
                          <NInputNumber v-model:value="editingSignal.stop_loss" :show-button="false" status="error">
                             <template #prefix>$</template>
                          </NInputNumber>
                       </NFormItem>
                       <!-- 预计止损盈亏 -->
                       <div v-if="estimatedStopLossProfit !== null" class="pnl-preview" :class="estimatedStopLossProfit >= 0 ? 'profit' : 'loss'">
                          预计: <span class="pnl-value">{{ estimatedStopLossProfit >= 0 ? '+' : '' }}{{ estimatedStopLossProfit.toFixed(2) }} USDT</span>
                       </div>
                    </NGi>
                    <NGi>
                       <NFormItem label="止盈价格 (Take Profit)">
                          <NInputNumber v-model:value="editingSignal.take_profit" :show-button="false" status="success">
                             <template #prefix>$</template>
                          </NInputNumber>
                       </NFormItem>
                       <!-- 预计止盈盈亏 -->
                       <div v-if="estimatedTakeProfitProfit !== null" class="pnl-preview" :class="estimatedTakeProfitProfit >= 0 ? 'profit' : 'loss'">
                          预计: <span class="pnl-value">{{ estimatedTakeProfitProfit >= 0 ? '+' : '' }}{{ estimatedTakeProfitProfit.toFixed(2) }} USDT</span>
                       </div>
                    </NGi>
                 </NGrid>

                 <!-- 仓位 -->
                 <div class="section-title mt-4">仓位管理</div>
                 <NGrid :cols="2" :x-gap="16">
                    <NGi>
                       <NFormItem label="杠杆倍数">
                          <NInputNumber v-model:value="editingSignal.leverage" :min="1" :max="125" />
                       </NFormItem>
                    </NGi>
                    <NGi>
                       <NFormItem>
                          <template #label>
                            <div class="flex items-center justify-between w-full">
                              <span>保证金 (USDT)</span>
                              <span class="text-xs text-gray-400">
                                可用: <span class="text-green-400 font-mono">{{ context?.wallet?.available?.toFixed(2) || '0.00' }}</span> USDT
                              </span>
                            </div>
                          </template>
                          <NInputNumber 
                            v-model:value="editingSignal.margin" 
                            :min="10" 
                            :max="context?.wallet?.available || 10000"
                            :placeholder="`最大 ${context?.wallet?.available?.toFixed(0) || '?'}`"
                          />
                       </NFormItem>
                    </NGi>
                 </NGrid>
               </template>

               <!-- ========== 网格交易模式 ========== -->
               <template v-else>
                 <!-- 网格区间 -->
                 <div class="section-title">网格区间设置</div>
                 <NGrid :cols="2" :x-gap="16">
                    <NGi>
                       <NFormItem label="网格下限 (Lower)">
                          <NInputNumber v-model:value="editingSignal.grid_lower" :show-button="false">
                             <template #prefix>$</template>
                          </NInputNumber>
                       </NFormItem>
                    </NGi>
                    <NGi>
                       <NFormItem label="网格上限 (Upper)">
                          <NInputNumber v-model:value="editingSignal.grid_upper" :show-button="false">
                             <template #prefix>$</template>
                          </NInputNumber>
                       </NFormItem>
                    </NGi>
                 </NGrid>

                 <!-- 网格参数 -->
                 <div class="section-title mt-4">网格参数</div>
                 <NGrid :cols="3" :x-gap="16">
                    <NGi>
                       <NFormItem label="网格数量">
                          <NInputNumber v-model:value="editingSignal.grid_count" :min="3" :max="200" />
                       </NFormItem>
                    </NGi>
                    <NGi>
                       <NFormItem label="网格类型">
                          <NSelect 
                            v-model:value="editingSignal.grid_type"
                            :options="[
                              { label: '等差', value: 'arithmetic' },
                              { label: '等比', value: 'geometric' }
                            ]"
                          />
                       </NFormItem>
                    </NGi>
                    <NGi>
                       <NFormItem label="交易方向">
                          <NSelect 
                            v-model:value="editingSignal.grid_direction"
                            :options="[
                              { label: '双向 (中性)', value: 'neutral' },
                              { label: '做多', value: 'long' },
                              { label: '做空', value: 'short' }
                            ]"
                          />
                       </NFormItem>
                    </NGi>
                 </NGrid>

                 <!-- 资金与风控 -->
                 <div class="section-title mt-4">资金与风控</div>
                 <NGrid :cols="3" :x-gap="16">
                    <NGi>
                       <NFormItem>
                          <template #label>
                            <div class="flex items-center justify-between w-full">
                              <span>投资总额</span>
                              <span class="text-xs text-gray-400">
                                可用: <span class="text-green-400 font-mono">{{ context?.wallet?.available?.toFixed(0) || '0' }}</span>
                              </span>
                            </div>
                          </template>
                          <NInputNumber 
                            v-model:value="editingSignal.grid_investment" 
                            :min="50"
                            :max="context?.wallet?.available || 10000"
                          >
                             <template #suffix>USDT</template>
                          </NInputNumber>
                       </NFormItem>
                    </NGi>
                    <NGi>
                       <NFormItem label="杠杆倍数">
                          <NInputNumber v-model:value="editingSignal.leverage" :min="1" :max="125" />
                       </NFormItem>
                    </NGi>
                    <NGi>
                       <NFormItem label="止损价格">
                          <NInputNumber v-model:value="editingSignal.stop_loss" :show-button="false" status="error">
                             <template #prefix>$</template>
                          </NInputNumber>
                       </NFormItem>
                    </NGi>
                 </NGrid>
               </template>
            </div>

            <div class="modal-actions">
               <NButton @click="showEditModal = false" ghost>取消</NButton>
               <NButton type="primary" @click="handleEditSave" color="#8a2be2">保存并更新</NButton>
            </div>
         </template>
      </NCard>
    </NModal>
  </div>
  </MainLayout>
</template>

<style scoped>
.signal-page {
  min-height: calc(100vh - 56px);
  padding: 24px;
  position: relative;
  overflow-x: hidden;
}

.bg-glow {
  position: absolute;
  top: -20%;
  left: 50%;
  transform: translateX(-50%);
  width: 800px;
  height: 800px;
  background: radial-gradient(circle, rgba(138,43,226,0.15) 0%, rgba(0,0,0,0) 70%);
  pointer-events: none;
  z-index: 0;
}

.page-header {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 32px;
  max-width: 1400px;
  margin-left: auto;
  margin-right: auto;
}

.title-section {
  display: flex;
  align-items: center;
}

.page-title {
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  margin: 0;
  letter-spacing: -0.5px;
}

.main-layout {
  position: relative;
  z-index: 1;
  max-width: 1400px;
  margin: 0 auto;
}

/* Dashboard Cards */
.dashboard-card {
  background: rgba(24, 24, 27, 0.6); /* Zinc 900 / 60% */
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  transition: transform 0.2s ease, border-color 0.2s;
  overflow: hidden;
  position: relative;
  margin-bottom: 16px;
}

.dashboard-card:hover {
  border-color: rgba(255, 255, 255, 0.15);
  transform: translateY(-2px);
}

.card-icon-bg {
  position: absolute;
  top: -10px;
  right: -10px;
  font-size: 100px;
  opacity: 0.05;
  color: #fff;
  pointer-events: none;
}

.card-icon-bg.success {
  color: #22c55e;
}

.market-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.market-header .label {
  font-size: 14px;
  color: #a1a1aa;
  font-weight: 500;
}

.market-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.price-display {
  font-size: 32px;
  font-weight: 700;
  color: #fff;
  line-height: 1;
  letter-spacing: -1px;
}

.price-display .currency {
  font-size: 20px;
  color: #71717a;
  margin-right: 4px;
}

.change-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 6px;
  width: fit-content;
}

.change-tag.up {
  color: #22c55e;
  background: rgba(34, 197, 94, 0.1);
}

.change-tag.down {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

.wallet-content {
  display: flex;
  flex-direction: column;
}

.balance-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.balance-row .sub-label {
  font-size: 13px;
  color: #71717a;
}

.balance-row .val {
  font-size: 15px;
  font-weight: 600;
  color: #e4e4e7;
}

.balance-row .val.highlight {
  color: #fff;
  font-size: 18px;
}

.status-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: rgba(255, 255, 255, 0.03);
  padding: 12px 0;
  border-radius: 8px;
}

.stat-item .num {
  font-size: 20px;
  font-weight: 700;
  color: #fff;
}

.stat-item .txt {
  font-size: 12px;
  color: #71717a;
  margin-top: 4px;
}

/* Terminal Card */
.terminal-card {
  background: #111 !important;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.terminal-input-wrapper {
  background: #000;
  border: 1px solid #333;
  border-radius: 8px;
  padding: 0;
  overflow: hidden;
  transition: border-color 0.2s;
}

.terminal-input-wrapper:focus-within {
  border-color: #8a2be2;
}

.terminal-input {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 14px;
  line-height: 1.6;
}

.terminal-footer {
  background: #18181b;
  padding: 8px;
  display: flex;
  justify-content: flex-end;
  border-top: 1px solid #333;
}

.analyze-btn {
  font-weight: 600;
  letter-spacing: 0.5px;
}

.quick-examples {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.example-tag {
  cursor: pointer;
  transition: all 0.2s;
  background: rgba(255, 255, 255, 0.05);
}

.example-tag:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

/* Result Card */
.result-card {
  margin-top: 24px;
  background: rgba(20, 20, 22, 0.8) !important;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  position: relative;
  overflow: hidden;
  box-shadow: 0 4px 24px rgba(0,0,0,0.3);
}

.result-glow {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 4px;
  background: linear-gradient(90deg, #8a2be2, #d946ef);
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.signal-badge {
  padding: 8px 16px;
  border-radius: 8px;
  font-weight: 800;
  font-size: 18px;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.signal-badge.long {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
  border: 1px solid rgba(34, 197, 94, 0.3);
}

.signal-badge.short {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

/* Symbol Badge (AI 检测的币种) */
.symbol-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px 6px 6px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.symbol-badge .symbol-name {
  font-weight: 700;
  font-size: 14px;
  color: #fff;
  letter-spacing: 0.5px;
}

.confidence-meter {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(0,0,0,0.3);
  padding: 6px 12px;
  border-radius: 20px;
}

.confidence-meter .label {
  font-size: 12px;
  color: #71717a;
}

.confidence-meter .val {
  font-weight: 700;
  color: #fff;
  min-width: 40px;
  text-align: right;
}

.signal-data-grid {
  display: grid;
  grid-template-columns: 1.5fr 1fr 1fr;
  gap: 16px;
  margin-bottom: 24px;
}

.data-block {
  background: rgba(255, 255, 255, 0.03);
  padding: 16px;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.data-block .label {
  font-size: 12px;
  color: #a1a1aa;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.data-block .value {
  font-size: 20px;
  font-weight: 700;
  color: #fff;
  letter-spacing: -0.5px;
}

.text-success { color: #22c55e !important; }
.text-error { color: #ef4444 !important; }
.text-warning { color: #eab308 !important; }
.text-purple { color: #a855f7 !important; }

/* 止盈止损预览标签 */
.preview-badge {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 4px;
}

.preview-badge.profit {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
}

.preview-badge.loss {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.data-block.ratio {
  border-left-color: #eab308 !important;
}

.signal-meta-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  padding: 0 16px;
}

.signal-meta-grid.grid-mode {
  grid-template-columns: repeat(5, 1fr);
}

/* 交易模式切换按钮 */
.trade-mode-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
  padding: 0 16px;
}

.mode-tab {
  flex: 1;
  padding: 10px 16px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: #a1a1aa;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.mode-tab:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.15);
}

.mode-tab.active {
  background: linear-gradient(135deg, rgba(138, 43, 226, 0.2) 0%, rgba(168, 85, 247, 0.2) 100%);
  border-color: #8a2be2;
  color: #e4e4e7;
}

.signal-data-grid.grid-mode .data-block.entry {
  border-left-color: #3b82f6;
}

.signal-data-grid.grid-mode .data-block.target {
  border-left-color: #3b82f6;
}

/* Modal mode tabs */
.modal-mode-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
}

.modal-mode-tab {
  flex: 1;
  padding: 10px 16px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: #a1a1aa;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.modal-mode-tab:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.15);
}

.modal-mode-tab.active {
  background: linear-gradient(135deg, rgba(138, 43, 226, 0.2) 0%, rgba(168, 85, 247, 0.2) 100%);
  border-color: #8a2be2;
  color: #e4e4e7;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-item .label {
  font-size: 12px;
  color: #71717a;
}

.meta-item .val {
  font-weight: 600;
  color: #e4e4e7;
}

.ai-reasoning {
  background: rgba(138, 43, 226, 0.05); /* Purple tint */
  border-left: 3px solid #8a2be2;
  padding: 16px;
  border-radius: 0 8px 8px 0;
  margin-bottom: 24px;
}

.reasoning-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #a78bfa;
  margin-bottom: 8px;
}

.reasoning-text {
  font-size: 14px;
  color: #d4d4d8;
  line-height: 1.6;
  margin: 0;
}

.warnings-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 24px;
}

.warning-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #fbbf24;
  background: rgba(245, 158, 11, 0.1);
  padding: 8px 12px;
  border-radius: 6px;
}

.action-bar {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.action-btn {
  min-width: 100px;
}

.action-btn.confirm {
  min-width: 140px;
  font-weight: 600;
}

/* Modal Styling */
:deep(.premium-modal) .n-card {
   background: #09090b;
   border: 1px solid #27272a;
   box-shadow: 0 20px 50px rgba(0,0,0,0.5);
}

.modal-header {
   display: flex;
   align-items: center;
   gap: 12px;
   font-size: 18px;
   font-weight: 700;
   color: #fff;
}

.section-title {
   font-size: 12px;
   font-weight: 600;
   color: #a1a1aa;
   text-transform: uppercase;
   margin-bottom: 12px;
}

.modal-actions {
   display: flex;
   justify-content: flex-end;
   gap: 12px;
   margin-top: 32px;
   padding-top: 24px;
   border-top: 1px solid #27272a;
}

/* Tasks Panel */
.tasks-panel {
   min-height: 400px;
}

.task-list {
   display: flex;
   flex-direction: column;
   gap: 8px;
}

.task-row {
   display: flex;
   align-items: center;
   gap: 12px;
   padding: 12px;
   background: rgba(255, 255, 255, 0.03);
   border-radius: 12px;
   transition: background 0.2s;
}

.task-row:hover {
   background: rgba(255, 255, 255, 0.06);
}

.task-icon {
   width: 32px;
   height: 32px;
   border-radius: 8px;
   display: flex;
   align-items: center;
   justify-content: center;
}

.task-icon.long {
   background: rgba(34, 197, 94, 0.1);
   color: #22c55e;
}

.task-icon.short {
   background: rgba(239, 68, 68, 0.1);
   color: #ef4444;
}

.task-info {
   flex: 1;
}

.task-top {
   display: flex;
   align-items: center;
   justify-content: space-between;
   margin-bottom: 2px;
}

.task-top .symbol {
   font-weight: 600;
   color: #fff;
}

.task-top .side {
   font-size: 10px;
   font-weight: 700;
   padding: 2px 6px;
   border-radius: 4px;
}

.task-top .side.long { color: #22c55e; background: rgba(34, 197, 94, 0.1); }
.task-top .side.short { color: #ef4444; background: rgba(239, 68, 68, 0.1); }

.task-btm {
   font-size: 12px;
   color: #71717a;
}

.empty-state {
   display: flex;
   flex-direction: column;
   align-items: center;
   justify-content: center;
   height: 300px;
   color: #52525b;
   gap: 12px;
}

/* Transitions */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.3s ease;
}

.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(20px);
}

/* 新增: 预计盈亏显示样式 */
.pnl-preview {
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 4px;
  margin-top: -8px;
  margin-bottom: 8px;
}

.pnl-preview.profit {
  color: #22c55e;
  background: rgba(34, 197, 94, 0.1);
}

.pnl-preview.loss {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

.pnl-preview .pnl-value {
  font-weight: 600;
  font-family: 'Inter', monospace;
}
</style>
