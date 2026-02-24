<script setup lang="ts">
/**
 * AutopilotDashboard - AI 自动交易控制面板
 * ==========================================
 * 独立页面: 配置 → 启动/停止 → 查看决策时间线
 *
 * 功能:
 * - 多交易对标签输入
 * - 决策间隔选择
 * - 启动/停止/手动触发
 * - 运行状态卡片
 * - 决策时间线 (可展开看 AI 思考过程)
 */

import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useMessage, NIcon, NSpin } from 'naive-ui'
import {
  PlayOutline,
  StopOutline,
  FlashOutline,
  TimeOutline,
  TrendingUpOutline,
  RefreshOutline,
  ChevronDownOutline,
  ChevronUpOutline,
  CloseOutline,
  AddOutline,
  TrashOutline,
} from '@vicons/ionicons5'
import MainLayout from '@/layouts/MainLayout.vue'
import {
  startAutopilot,
  stopAutopilot,
  runOnceAutopilot,
  getAutopilotStatus,
  getAutopilotLogs,
  clearAutopilotLogs,
  type AutopilotStatus,
  type AutopilotLogResponse,
} from '@/api/chat'
import { formatDateTimeBJ } from '@/utils/time'

// ==================== State ====================
const message = useMessage()

// Config
const symbols = ref<string[]>(['BTCUSDT'])
const newSymbol = ref('')
const interval = ref('15m')
const selectedIntervals = ref<string[]>(['5m', '1h', '4h'])

// Status
const status = ref<AutopilotStatus>({
  running: false,
  symbols: [],
  interval: '15m',
  started_at: null,
  total_cycles: 0,
  last_cycle_at: null,
  actions_taken: 0,
})

// Logs
const logs = ref<AutopilotLogResponse[]>([])
const logsLoading = ref(false)
const expandedLogId = ref<number | null>(null)
const activeLogSymbol = ref<string | null>(null) // 新增：当前查看日志的交易对

// UI
const loading = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

// ==================== Computed ====================

const intervalOptions = [
  { label: '5 分钟', value: '5m' },
  { label: '15 分钟', value: '15m' },
  { label: '30 分钟', value: '30m' },
  { label: '1 小时', value: '1h' },
  { label: '4 小时', value: '4h' },
]

const decisionColors: Record<string, string> = {
  hold: '#8b8b8b',
  open_long: '#52c41a',
  open_short: '#ff4d4f',
  close_long: '#faad14',
  close_short: '#faad14',
  error: '#ff4d4f',
}

const decisionLabels: Record<string, string> = {
  hold: '观望',
  open_long: '做多',
  open_short: '做空',
  close_long: '平多',
  close_short: '平空',
  error: '异常',
}

// 来源标签
const sourceLabels: Record<string, string> = {
  autopilot: 'Autopilot',
  agent: 'AI Agent',
  news: '新闻监控',
  quant: '量化策略',
}
const sourceColors: Record<string, string> = {
  autopilot: '#8b5cf6',
  agent: '#3b82f6',
  news: '#f59e0b',
  quant: '#10b981',
}

// 基于选择的交易对过滤日志
const filteredLogs = computed(() => {
  if (!activeLogSymbol.value) return logs.value
  return logs.value.filter(l => l.symbol === activeLogSymbol.value)
})

// 决策统计 (computed, 纯前端计算，基于过滤后的日志)
const decisionStats = computed(() => {
  const hold = filteredLogs.value.filter(l => l.decision === 'hold').length
  const openTrades = filteredLogs.value.filter(l => l.decision === 'open_long' || l.decision === 'open_short').length
  const closeTrades = filteredLogs.value.filter(l => l.decision === 'close_long' || l.decision === 'close_short').length
  const actions = filteredLogs.value.filter(l => l.action_taken).length
  const errors = filteredLogs.value.filter(l => l.error_message).length
  return { hold, openTrades, closeTrades, actions, errors, total: filteredLogs.value.length }
})

// 最近决策走势 (最后 20 次决策)
const recentTrend = computed(() => {
  return [...filteredLogs.value].reverse().slice(-20).map(l => l.decision)
})

const runDuration = computed(() => {
  if (!status.value.started_at) return '-'
  const start = new Date(status.value.started_at)
  const now = new Date()
  const diffMin = Math.floor((now.getTime() - start.getTime()) / 60000)
  if (diffMin < 60) return `${diffMin} 分钟`
  return `${Math.floor(diffMin / 60)} 小时 ${diffMin % 60} 分钟`
})

// ==================== Lifecycle ====================

onMounted(async () => {
  await pollStatus()
  await fetchLogs()
  pollTimer = setInterval(async () => {
    await pollStatus()
    if (status.value.running) {
      await fetchLogs()
    }
  }, 10000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

// ==================== Methods ====================

async function pollStatus() {
  try {
    status.value = await getAutopilotStatus()
    if (status.value.running && status.value.symbols.length > 0) {
      symbols.value = [...status.value.symbols]
      // interval 不从服务器同步，允许用户自由修改
    }
  } catch { /* ignore */ }
}

async function fetchLogs() {
  logsLoading.value = true
  try {
    // 只获取当前会话的日志
    const since = status.value.started_at || undefined
    logs.value = await getAutopilotLogs(50, undefined, since)
  } catch { /* ignore */ }
  logsLoading.value = false
}

function addSymbol() {
  const s = newSymbol.value.toUpperCase().trim()
  if (s && !symbols.value.includes(s)) {
    symbols.value.push(s)
  }
  newSymbol.value = ''
}

function removeSymbol(sym: string) {
  symbols.value = symbols.value.filter(s => s !== sym)
}

async function handleStart() {
  if (symbols.value.length === 0) {
    message.warning('请至少添加一个交易对')
    return
  }
  loading.value = true
  try {
    await startAutopilot({ symbols: symbols.value, interval: interval.value, intervals: selectedIntervals.value })
    message.success('自动交易已启动')
    await pollStatus()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '启动失败')
  }
  loading.value = false
}

async function handleStop() {
  loading.value = true
  try {
    await stopAutopilot()
    message.success('自动交易已停止')
    await pollStatus()
  } catch {
    message.error('停止失败')
  }
  loading.value = false
}

async function handleRunOnce() {
  loading.value = true
  try {
    for (const sym of symbols.value) {
      await runOnceAutopilot(sym)
    }
    message.success('已触发一次分析')
    await fetchLogs()
  } catch {
    message.error('触发失败')
  }
  loading.value = false
}

function toggleExpand(logId: number) {
  expandedLogId.value = expandedLogId.value === logId ? null : logId
}

function toggleInterval(val: string) {
  const idx = selectedIntervals.value.indexOf(val)
  if (idx >= 0) {
    if (selectedIntervals.value.length > 1) {
      selectedIntervals.value.splice(idx, 1)
    }
  } else {
    selectedIntervals.value.push(val)
  }
}

async function handleClearLogs() {
  if (logs.value.length === 0) return
  loading.value = true
  try {
    await clearAutopilotLogs()
    logs.value = []
    message.success('已清空决策记录')
  } catch {
    message.error('清空失败')
  }
  loading.value = false
}

const formatTime = formatDateTimeBJ
</script>

<template>
  <MainLayout>
    <div class="autopilot-page">
      <!-- 页面标题 -->
      <div class="page-header fade-in">
        <div class="header-left">
          <div class="header-icon">
            <NIcon :component="TrendingUpOutline" :size="24" />
          </div>
          <div>
            <h1>AI 自动交易</h1>
            <p class="header-desc">AI Agent 定时分析市场并自主决策交易</p>
          </div>
        </div>
        <div class="header-actions">
          <button
            class="btn btn-ghost"
            @click="fetchLogs"
            :disabled="logsLoading"
          >
            <NIcon :component="RefreshOutline" :size="16" />
            刷新
          </button>
        </div>
      </div>

      <!-- 状态卡片 -->
      <div class="status-cards">
        <div :class="['status-card slide-up', status.running ? 'active' : 'inactive']" style="animation-delay: 0.1s">
          <div class="card-icon">
            <div :class="['pulse-dot', { running: status.running }]"></div>
          </div>
          <div class="card-info">
            <div class="card-label">状态</div>
            <div class="card-value">
              {{ status.running ? '运行中' : '已停止' }}
            </div>
          </div>
        </div>

        <div class="status-card slide-up" style="animation-delay: 0.2s">
          <div class="card-icon">
            <NIcon :component="TimeOutline" :size="20" style="color: #8b5cf6;" />
          </div>
          <div class="card-info">
            <div class="card-label">运行时长</div>
            <div class="card-value">{{ status.running ? runDuration : '-' }}</div>
          </div>
        </div>

        <div class="status-card slide-up" style="animation-delay: 0.3s">
          <div class="card-icon">
            <NIcon :component="FlashOutline" :size="20" style="color: #f59e0b;" />
          </div>
          <div class="card-info">
            <div class="card-label">分析次数</div>
            <div class="card-value">{{ status.total_cycles }}</div>
          </div>
        </div>

        <div class="status-card slide-up" style="animation-delay: 0.4s">
          <div class="card-icon">
            <NIcon :component="TrendingUpOutline" :size="20" style="color: #10b981;" />
          </div>
          <div class="card-info">
            <div class="card-label">执行操作</div>
            <div class="card-value">{{ status.actions_taken }}</div>
          </div>
        </div>
      </div>

      <!-- 配置 + 时间线 双栏 -->
      <div class="main-content">
        <!-- 左侧: 配置面板 -->
        <div class="config-panel glass-panel slide-up" style="animation-delay: 0.5s">
          <h3 class="panel-title">交易配置</h3>

          <!-- 交易对标签 -->
          <div class="config-section">
            <label>监控交易对</label>
            <div class="symbol-tags">
              <span
                v-for="sym in symbols"
                :key="sym"
                class="symbol-tag"
              >
                {{ sym }}
                <button class="tag-remove" @click="removeSymbol(sym)" :disabled="status.running">
                  <NIcon :component="CloseOutline" :size="12" />
                </button>
              </span>
            </div>
            <div class="symbol-input-row" v-if="!status.running">
              <input
                v-model="newSymbol"
                placeholder="输入交易对如 ETHUSDT"
                @keyup.enter="addSymbol"
                class="form-input"
              />
              <button class="btn btn-sm" @click="addSymbol">
                <NIcon :component="AddOutline" :size="14" />
              </button>
            </div>
          </div>

          <!-- 分析间隔 -->
          <div class="config-section">
            <label class="form-label">分析间隔</label>
            <select
              v-model="interval"
              class="form-select"
            >
              <option v-for="opt in intervalOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>

          <!-- 指标级别 -->
          <div class="config-section">
            <label class="form-label">指标K线级别 <span class="hint">(可多选)</span></label>
            <div class="interval-toggles">
              <button
                v-for="opt in intervalOptions"
                :key="opt.value"
                :class="['interval-chip', { active: selectedIntervals.includes(opt.value) }]"
                :disabled="status.running"
                @click="toggleInterval(opt.value)"
              >
                {{ opt.value }}
              </button>
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="action-buttons">
            <button
              v-if="!status.running"
              class="btn btn-primary btn-lg"
              @click="handleStart"
              :disabled="loading || symbols.length === 0"
            >
              <NIcon :component="PlayOutline" :size="18" />
              启动自动交易
            </button>
            <button
              v-else
              class="btn btn-danger btn-lg"
              @click="handleStop"
              :disabled="loading"
            >
              <NIcon :component="StopOutline" :size="18" />
              停止
            </button>

            <button
              class="btn btn-ghost btn-lg"
              @click="handleRunOnce"
              :disabled="loading"
            >
              <NIcon :component="FlashOutline" :size="18" />
              手动触发一次
            </button>
          </div>
        </div>

        <!-- 右侧: 决策时间线 -->
        <div class="timeline-panel">
          <h3 class="panel-title">
            <div style="display: flex; align-items: center; gap: 8px;">
              决策记录
              <span class="log-count" v-if="filteredLogs.length > 0">{{ filteredLogs.length }}</span>
            </div>
            
            <div class="log-symbol-tabs" v-if="symbols.length > 0">
              <button 
                class="log-tab" 
                :class="{ active: activeLogSymbol === null }"
                @click="activeLogSymbol = null"
              >全部</button>
              <button 
                v-for="sym in symbols" 
                :key="sym"
                class="log-tab"
                :class="{ active: activeLogSymbol === sym }"
                @click="activeLogSymbol = sym"
              >{{ sym }}</button>
            </div>

            <button
              v-if="logs.length > 0"
              class="btn btn-ghost btn-xs clear-logs-btn"
              @click.stop="handleClearLogs"
              :disabled="loading"
              title="清空所有记录"
              style="margin-left: auto;"
            >
              <NIcon :component="TrashOutline" :size="14" />
              清空
            </button>
          </h3>

          <!-- 决策统计摘要 -->
          <div class="decision-stats" v-if="filteredLogs.length > 0">
            <div class="dstat-item">
              <span class="dstat-num" style="color: #8b8b8b;">{{ decisionStats.hold }}</span>
              <span class="dstat-label">观望</span>
            </div>
            <div class="dstat-divider" />
            <div class="dstat-item">
              <span class="dstat-num" style="color: #52c41a;">{{ decisionStats.openTrades }}</span>
              <span class="dstat-label">开仓</span>
            </div>
            <div class="dstat-divider" />
            <div class="dstat-item">
              <span class="dstat-num" style="color: #faad14;">{{ decisionStats.closeTrades }}</span>
              <span class="dstat-label">平仓</span>
            </div>
            <div class="dstat-divider" />
            <div class="dstat-item">
              <span class="dstat-num" style="color: #22c55e;">{{ decisionStats.actions }}</span>
              <span class="dstat-label">已执行</span>
            </div>
            <div class="dstat-divider" v-if="decisionStats.errors > 0" />
            <div class="dstat-item" v-if="decisionStats.errors > 0">
              <span class="dstat-num" style="color: #ff4d4f;">{{ decisionStats.errors }}</span>
              <span class="dstat-label">异常</span>
            </div>
            <div class="dstat-divider" />
            <div class="trend-sparkline" title="最近20次决策趋势 (左旧右新)">
              <div 
                v-for="(dec, idx) in recentTrend" 
                :key="idx"
                class="trend-dot"
                :style="{ background: decisionColors[dec] || '#666' }"
              />
            </div>
          </div>

          <div v-if="logsLoading && filteredLogs.length === 0" class="timeline-loading">
            <NSpin size="small" />
            <span>加载中...</span>
          </div>

          <div v-else-if="logs.length === 0" class="timeline-empty">
            <p>暂无决策记录</p>
            <p class="text-hint">启动自动交易后，AI 的每次分析都会记录在这里</p>
          </div>
          
          <div v-else-if="filteredLogs.length === 0" class="timeline-empty">
            <p>该交易对暂无日志</p>
          </div>

          <div v-else class="timeline">
            <div
              v-for="log in filteredLogs"
              :key="log.id"
              class="timeline-item"
              @click="toggleExpand(log.id)"
            >
              <!-- 时间线标记 -->
              <div class="timeline-marker">
                <div
                  class="marker-dot"
                  :style="{ background: decisionColors[log.decision] || '#666' }"
                ></div>
                <div class="marker-line"></div>
              </div>

              <!-- 卡片内容 -->
              <div class="timeline-card" :style="{ borderLeftColor: decisionColors[log.decision] || '#666' }">
                <div class="card-header">
                  <span class="decision-badge" :style="{ color: decisionColors[log.decision] || '#666' }">
                    {{ log.action_taken ? (decisionLabels[log.decision] || log.decision) : (log.decision === 'hold' ? '观望' : '分析:' + (decisionLabels[log.decision] || log.decision)) }}
                  </span>
                  <span
                    class="source-badge"
                    :style="{ background: sourceColors[log.source || 'autopilot'] || '#666', color: '#fff' }"
                  >
                    {{ sourceLabels[log.source || 'autopilot'] || log.source || 'Autopilot' }}
                  </span>
                  <span class="symbol-label">{{ log.symbol }}</span>
                  <span class="time-label">{{ formatTime(log.created_at) }}</span>
                  <NIcon
                    :component="expandedLogId === log.id ? ChevronUpOutline : ChevronDownOutline"
                    :size="14"
                    style="color: #666; margin-left: auto;"
                  />
                </div>

                <div class="card-summary">{{ log.summary }}</div>

                <!-- 展开详情 -->
                <div v-if="expandedLogId === log.id" class="card-detail">
                  <div class="detail-section" v-if="log.action_taken">
                    <span class="detail-label">已执行操作</span>
                    <span v-if="log.order_id" class="detail-value">订单 #{{ log.order_id }}</span>
                  </div>
                  <div class="detail-section" v-if="log.error_message">
                    <span class="detail-label">错误</span>
                    <span class="detail-value error">{{ log.error_message }}</span>
                  </div>
                  <div class="thinking-block">
                    <div class="thinking-label">AI 思考过程</div>
                    <pre class="thinking-content">{{ log.thinking }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </MainLayout>
</template>

<style scoped>
.autopilot-page {
  max-width: 1400px;
  margin: 0 auto;
  padding-bottom: 40px;
}

/* ==== Page Header ==== */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.2), rgba(16, 185, 129, 0.2));
  display: flex;
  align-items: center;
  justify-content: center;
  color: #8b5cf6;
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.15);
}

.page-header h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: #f0f0f0;
  letter-spacing: -0.5px;
}

.header-desc {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.header-actions {
  display: flex;
  gap: 12px;
}

/* ==== Status Cards ==== */
.status-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 32px;
}

.status-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 24px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.status-card:hover {
  transform: translateY(-2px);
  border-color: rgba(255, 255, 255, 0.12);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
}

.status-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(45deg, transparent, rgba(255, 255, 255, 0.03), transparent);
  transform: translateX(-100%);
  transition: transform 0.6s;
}

.status-card:hover::before {
  transform: translateX(100%);
}

.status-card.active {
  border-color: rgba(16, 185, 129, 0.3);
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.05), rgba(16, 185, 129, 0.02));
}

.status-card.inactive {
  border-color: rgba(255, 255, 255, 0.06);
}

.card-icon {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 10px;
}

.card-info {
  display: flex;
  flex-direction: column;
}

.card-label {
  font-size: 12px;
  color: var(--color-text-secondary);
  font-weight: 500;
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.card-value {
  font-size: 20px;
  font-weight: 700;
  color: #f0f0f0;
  font-family: var(--font-family-mono);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.5px;
}

.pulse-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #555;
  transition: all 0.3s;
}

.pulse-dot.running {
  background: conic-gradient(from 0deg, #8b5cf6, #3b82f6, #10b981, #8b5cf6);
  box-shadow: 0 0 12px rgba(16, 185, 129, 0.4);
  animation: spin 2s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ==== Main Content ==== */
.main-content {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 32px;
  min-height: 600px;
}

/* ==== Config Panel ==== */
.config-panel {
  border-radius: 16px;
  padding: 24px;
  height: fit-content;
  position: sticky;
  top: 20px;
}

.panel-title {
  font-size: 16px;
  font-weight: 600;
  color: #e0e0e0;
  margin: 0 0 24px;
  display: flex;
  align-items: center;
  gap: 12px;
  position: relative;
}

.panel-title::before {
  content: '';
  display: block;
  width: 3px;
  height: 16px;
  background: var(--color-cyber-purple);
  border-radius: 2px;
}

.log-count {
  background: rgba(139, 92, 246, 0.15);
  color: #a78bfa;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-family-mono);
}

/* Decision Stats */
.decision-stats {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  margin-bottom: 16px;
}

.dstat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 42px;
}

.dstat-num {
  font-size: 18px;
  font-weight: 700;
  font-family: 'SF Mono', monospace;
}

.dstat-label {
  font-size: 10px;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.dstat-divider {
  width: 1px;
  height: 28px;
  background: rgba(255, 255, 255, 0.08);
}

.trend-sparkline {
  display: flex;
  align-items: center;
  gap: 3px;
  margin-left: auto; /* Push to right */
  padding-left: 10px;
}

.trend-dot {
  width: 6px;
  height: 12px;
  border-radius: 2px;
  opacity: 0.8;
}

.log-symbol-tabs {
  display: flex;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 6px;
  padding: 3px;
  margin-left: 16px;
}

.log-tab {
  background: transparent;
  border: none;
  font-size: 12px;
  color: #9ca3af;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.log-tab:hover {
  color: #e5e7eb;
}

.log-tab.active {
  background: rgba(139, 92, 246, 0.3);
  color: #d8b4fe;
  font-weight: 500;
}

.config-section {
  margin-bottom: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.config-section:last-of-type {
  border-bottom: none;
  padding-bottom: 0;
  margin-bottom: 0;
}

.symbol-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.symbol-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(139, 92, 246, 0.12);
  color: #d8b4fe;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-family-mono);
  border: 1px solid rgba(139, 92, 246, 0.2);
  transition: all 0.2s;
}

.symbol-tag:hover {
  background: rgba(139, 92, 246, 0.2);
  border-color: rgba(139, 92, 246, 0.4);
}

.tag-remove {
  background: none;
  border: none;
  color: #a78bfa;
  cursor: pointer;
  padding: 2px;
  display: flex;
  opacity: 0.7;
  border-radius: 4px;
  transition: all 0.2s;
}

.tag-remove:hover {
  opacity: 1;
  background: rgba(255, 255, 255, 0.1);
}

.symbol-input-row {
  display: flex;
  gap: 10px;
}

/* ==== Interval Toggle Chips ==== */
.interval-toggles {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.interval-chip {
  padding: 8px 16px;
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: #999;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  font-family: var(--font-family-sans);
  position: relative;
  overflow: hidden;
}

.interval-chip:hover:not(:disabled) {
  border-color: rgba(139, 92, 246, 0.4);
  color: #ccc;
  transform: translateY(-1px);
}

.interval-chip.active {
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.25), rgba(59, 130, 246, 0.15));
  border-color: rgba(139, 92, 246, 0.5);
  color: #fff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.1), 0 4px 12px rgba(139, 92, 246, 0.15);
  padding-left: 20px;
}

.interval-chip.active::before {
  content: '';
  position: absolute;
  left: 8px;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 0 4px #fff;
}

.interval-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  filter: grayscale(100%);
}

.hint {
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 400;
  margin-left: 4px;
}

/* ==== Action Buttons ==== */
.action-buttons {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 32px;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  padding: 10px 20px;
  outline: none;
  position: relative;
  overflow: hidden;
}

.btn::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(rgba(255, 255, 255, 0.1), transparent);
  opacity: 0;
  transition: opacity 0.2s;
}

.btn:hover::after {
  opacity: 1;
}

.btn:active {
  transform: scale(0.98);
}

.btn-primary {
  background: linear-gradient(135deg, #8b5cf6, #6d28d9);
  color: white;
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
}

.btn-primary:hover {
  box-shadow: 0 6px 16px rgba(139, 92, 246, 0.4);
}

.btn-danger {
  background: linear-gradient(135deg, #ef4444, #dc2626);
  color: white;
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.3);
}

.btn-danger:hover {
  box-shadow: 0 6px 16px rgba(239, 68, 68, 0.4);
}

.btn-ghost {
  background: rgba(255, 255, 255, 0.05);
  color: #ccc;
  border: 1px solid transparent;
}

.btn-ghost:hover {
  background: rgba(255, 255, 255, 0.1);
  color: white;
  border-color: rgba(255, 255, 255, 0.1);
}

.btn-sm {
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(139, 92, 246, 0.15);
  color: #a78bfa;
}

.btn-sm:hover {
  background: rgba(139, 92, 246, 0.25);
}

.btn-lg {
  padding: 14px 24px;
  font-size: 15px;
  letter-spacing: 0.5px;
}

/* ==== Timeline ==== */
.timeline-panel {
  position: relative;
}

.clear-logs-btn {
  margin-left: auto;
  font-size: 12px;
  color: var(--color-text-secondary) !important;
  padding: 4px 10px !important;
  border-radius: 20px !important;
  background: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid transparent !important;
}

.clear-logs-btn:hover {
  color: #ff4d4f !important;
  background: rgba(255, 77, 79, 0.1) !important;
  border-color: rgba(255, 77, 79, 0.2) !important;
  box-shadow: 0 0 12px rgba(255, 77, 79, 0.15) !important;
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding-left: 10px;
}

.timeline-item {
  display: flex;
  gap: 20px;
  cursor: pointer;
  group: 1;
}

.timeline-marker {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 8px;
}

.marker-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  box-shadow: 0 0 0 4px rgba(0, 0, 0, 0.5);
  z-index: 2;
  position: relative;
}

/* Pulse animation for the latest dot */
.timeline-item:first-child .marker-dot::after {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  background: inherit;
  opacity: 0.4;
  animation: ping 1.5s cubic-bezier(0, 0, 0.2, 1) infinite;
}

@keyframes ping {
  75%, 100% { transform: scale(2); opacity: 0; }
}

.marker-line {
  width: 2px;
  flex: 1;
  background: rgba(255, 255, 255, 0.06);
  margin-top: 4px;
  border-radius: 1px;
}

.timeline-item:last-child .marker-line {
  display: none;
}

.timeline-card {
  flex: 1;
  background: rgba(20, 20, 32, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  padding: 16px;
  transition: all 0.25s;
  border-left: 3px solid transparent; /* Set via inline style */
}

.timeline-item:hover .timeline-card {
  background: rgba(255, 255, 255, 0.04);
  transform: translateX(4px);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.decision-badge {
  font-size: 13px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 100px;
  background: rgba(255, 255, 255, 0.05); /* Fallback */
  border: 1px solid rgba(255, 255, 255, 0.05);
  letter-spacing: 0.3px;
}

.source-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  letter-spacing: 0.3px;
  text-transform: uppercase;
  white-space: nowrap;
}

.symbol-label {
  font-size: 13px;
  font-weight: 600;
  color: #e0e0e0;
  font-family: var(--font-family-mono);
}

.time-label {
  font-size: 12px;
  color: var(--color-text-muted);
  font-family: var(--font-family-mono);
}

.card-summary {
  font-size: 14px;
  line-height: 1.6;
  color: #ccc;
}

/* Expanded Detail */
.card-detail {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px dashed rgba(255, 255, 255, 0.1);
  animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.detail-section {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
}

.detail-label {
  color: var(--color-text-secondary);
}

.detail-value {
  font-family: var(--font-family-mono);
  color: #e0e0e0;
}

.error {
  color: #ff4d4f;
}

.thinking-block {
  margin-top: 12px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid rgba(255, 255, 255, 0.03);
}

.thinking-label {
  font-size: 12px;
  color: #8b5cf6;
  margin-bottom: 8px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.thinking-content {
  font-size: 12px;
  color: #aaa;
  white-space: pre-wrap;
  font-family: var(--font-family-mono);
  max-height: 300px;
  overflow-y: auto;
  line-height: 1.5;
}

.timeline-loading, .timeline-empty {
  padding: 40px;
  text-align: center;
  color: var(--color-text-muted);
  background: rgba(255, 255, 255, 0.02);
  border-radius: 12px;
  border: 1px dashed rgba(255, 255, 255, 0.1);
}

.timeline-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.text-hint {
  font-size: 13px;
  margin-top: 8px;
  color: var(--color-text-secondary);
}

/* ========== Mobile Responsive ========== */
@media (max-width: 768px) {
  .autopilot-page {
    padding: 8px;
  }
  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .status-cards {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
  }
  .status-card {
    padding: 12px;
  }
  .card-value {
    font-size: 20px;
  }
  .main-content {
    grid-template-columns: 1fr;
    gap: 16px;
    min-height: auto;
  }
  .config-panel {
    position: static;
    padding: 16px;
  }
  .glass-panel {
    padding: 16px;
  }
  .timeline-entry {
    padding: 12px;
  }
}
</style>
