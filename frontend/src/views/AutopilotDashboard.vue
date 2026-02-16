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
  open_long: '开多',
  open_short: '开空',
  close_long: '平多',
  close_short: '平空',
  error: '异常',
}

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
      interval.value = status.value.interval
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

function formatTime(iso: string): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
</script>

<template>
  <MainLayout>
    <div class="autopilot-page">
      <!-- 页面标题 -->
      <div class="page-header">
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
        <div :class="['status-card', status.running ? 'active' : 'inactive']">
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

        <div class="status-card">
          <div class="card-icon">
            <NIcon :component="TimeOutline" :size="20" style="color: #8b5cf6;" />
          </div>
          <div class="card-info">
            <div class="card-label">运行时长</div>
            <div class="card-value">{{ status.running ? runDuration : '-' }}</div>
          </div>
        </div>

        <div class="status-card">
          <div class="card-icon">
            <NIcon :component="FlashOutline" :size="20" style="color: #f59e0b;" />
          </div>
          <div class="card-info">
            <div class="card-label">分析次数</div>
            <div class="card-value">{{ status.total_cycles }}</div>
          </div>
        </div>

        <div class="status-card">
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
        <div class="config-panel">
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
                class="config-input"
              />
              <button class="btn btn-sm" @click="addSymbol">
                <NIcon :component="AddOutline" :size="14" />
              </button>
            </div>
          </div>

          <!-- 分析间隔 -->
          <div class="config-section">
            <label>分析间隔</label>
            <select
              v-model="interval"
              class="config-select"
              :disabled="status.running"
            >
              <option v-for="opt in intervalOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>

          <!-- 指标级别 -->
          <div class="config-section">
            <label>指标K线级别 <span class="hint">(可多选)</span></label>
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
            决策记录
            <span class="log-count" v-if="logs.length > 0">{{ logs.length }}</span>
            <button
              v-if="logs.length > 0"
              class="btn btn-ghost btn-xs clear-logs-btn"
              @click.stop="handleClearLogs"
              :disabled="loading"
              title="清空记录"
            >
              <NIcon :component="TrashOutline" :size="14" />
              清空
            </button>
          </h3>

          <div v-if="logsLoading && logs.length === 0" class="timeline-loading">
            <NSpin size="small" />
            <span>加载中...</span>
          </div>

          <div v-else-if="logs.length === 0" class="timeline-empty">
            <p>暂无决策记录</p>
            <p class="text-hint">启动自动交易后，AI 的每次分析都会记录在这里</p>
          </div>

          <div v-else class="timeline">
            <div
              v-for="log in logs"
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
              <div class="timeline-card">
                <div class="card-header">
                  <span class="decision-badge" :style="{ color: decisionColors[log.decision] || '#666' }">
                    {{ log.action_taken ? (decisionLabels[log.decision] || log.decision) : (log.decision === 'hold' ? '观望' : '分析:' + (decisionLabels[log.decision] || log.decision)) }}
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
}

/* ==== Page Header ==== */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
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
}

.page-header h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: #f0f0f0;
}

.header-desc {
  margin: 2px 0 0;
  font-size: 13px;
  color: #666;
}

.header-actions {
  display: flex;
  gap: 8px;
}

/* ==== Status Cards ==== */
.status-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.status-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  transition: border-color 0.2s;
}

.status-card:hover {
  border-color: rgba(255, 255, 255, 0.12);
}

.status-card.active {
  border-color: rgba(82, 196, 26, 0.3);
  background: rgba(82, 196, 26, 0.05);
}

.status-card.inactive {
  border-color: rgba(255, 255, 255, 0.06);
}

.card-icon {
  flex-shrink: 0;
}

.card-label {
  font-size: 12px;
  color: #888;
  margin-bottom: 2px;
}

.card-value {
  font-size: 18px;
  font-weight: 600;
  color: #f0f0f0;
  font-family: 'Courier New', monospace;
}

.pulse-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #555;
}

.pulse-dot.running {
  background: #52c41a;
  box-shadow: 0 0 8px #52c41a;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 8px #52c41a; }
  50% { opacity: 0.5; box-shadow: 0 0 16px #52c41a; }
}

/* ==== Main Content ==== */
.main-content {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 24px;
  min-height: 500px;
}

/* ==== Config Panel ==== */
.config-panel {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  padding: 24px;
  height: fit-content;
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: #e0e0e0;
  margin: 0 0 20px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.log-count {
  background: rgba(139, 92, 246, 0.2);
  color: #8b5cf6;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 500;
}

.config-section {
  margin-bottom: 20px;
}

.config-section label {
  display: block;
  font-size: 13px;
  color: #999;
  margin-bottom: 8px;
}

.symbol-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.symbol-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: rgba(139, 92, 246, 0.12);
  color: #a78bfa;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  font-family: 'Courier New', monospace;
}

.tag-remove {
  background: none;
  border: none;
  color: #a78bfa;
  cursor: pointer;
  padding: 0;
  display: flex;
  opacity: 0.6;
}

.tag-remove:hover {
  opacity: 1;
}

.symbol-input-row {
  display: flex;
  gap: 8px;
}

.config-input {
  flex: 1;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 8px 12px;
  color: #ddd;
  font-size: 13px;
  outline: none;
}

.config-input:focus {
  border-color: rgba(139, 92, 246, 0.5);
}

.config-select {
  width: 100%;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 10px 12px;
  color: #ddd;
  font-size: 13px;
  outline: none;
}

.config-select:disabled {
  opacity: 0.5;
}

/* ==== Interval Toggle Chips ==== */
.interval-toggles {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.interval-chip {
  padding: 6px 14px;
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: #888;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  font-family: 'Courier New', monospace;
}

.interval-chip:hover:not(:disabled) {
  border-color: rgba(139, 92, 246, 0.4);
  color: #bbb;
}

.interval-chip.active {
  background: rgba(139, 92, 246, 0.2);
  border-color: rgba(139, 92, 246, 0.6);
  color: #a78bfa;
  box-shadow: 0 0 8px rgba(139, 92, 246, 0.15);
}

.interval-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.hint {
  color: #666;
  font-size: 11px;
  font-weight: 400;
}

/* ==== Clear Logs ==== */
.clear-logs-btn {
  margin-left: auto;
  font-size: 12px;
  color: #888 !important;
  padding: 2px 8px !important;
}

.clear-logs-btn:hover {
  color: #ff4d4f !important;
}

.btn-xs {
  padding: 2px 8px;
  font-size: 12px;
  border-radius: 6px;
}

.action-buttons {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 24px;
}

/* ==== Buttons ==== */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  padding: 8px 16px;
}

.btn-sm {
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(139, 92, 246, 0.15);
  color: #a78bfa;
}

.btn-sm:hover {
  background: rgba(139, 92, 246, 0.25);
}

.btn-lg {
  padding: 12px 20px;
  font-size: 14px;
}

.btn-primary {
  background: linear-gradient(135deg, #7c3aed, #5b21b6);
  color: #fff;
}

.btn-primary:hover {
  background: linear-gradient(135deg, #8b5cf6, #6d28d9);
  box-shadow: 0 4px 16px rgba(139, 92, 246, 0.3);
}

.btn-danger {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.btn-danger:hover {
  background: rgba(239, 68, 68, 0.25);
}

.btn-ghost {
  background: rgba(255, 255, 255, 0.06);
  color: #999;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.btn-ghost:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ddd;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ==== Timeline Panel ==== */
.timeline-panel {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  padding: 24px;
  overflow-y: auto;
  max-height: 700px;
}

.timeline-loading,
.timeline-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: #888;
  gap: 12px;
}

.text-hint {
  font-size: 13px;
  color: #555;
}

/* ==== Timeline ==== */
.timeline {
  display: flex;
  flex-direction: column;
}

.timeline-item {
  display: flex;
  gap: 16px;
  cursor: pointer;
  position: relative;
}

.timeline-marker {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 16px;
  flex-shrink: 0;
}

.marker-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #555;
  margin-top: 6px;
  z-index: 1;
  flex-shrink: 0;
}

.marker-line {
  width: 2px;
  flex: 1;
  background: rgba(255, 255, 255, 0.06);
  min-height: 16px;
}

.timeline-item:last-child .marker-line {
  display: none;
}

.timeline-card {
  flex: 1;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 12px;
  transition: border-color 0.2s;
}

.timeline-card:hover {
  border-color: rgba(139, 92, 246, 0.3);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.decision-badge {
  font-size: 13px;
  font-weight: 600;
}

.symbol-label {
  font-size: 12px;
  color: #a78bfa;
  background: rgba(139, 92, 246, 0.1);
  padding: 2px 8px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
}

.time-label {
  font-size: 12px;
  color: #666;
}

.card-summary {
  font-size: 13px;
  color: #aaa;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* ==== Expanded Detail ==== */
.card-detail {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.detail-section {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
}

.detail-label {
  color: #999;
}

.detail-value {
  color: #ddd;
  font-family: 'Courier New', monospace;
}

.detail-value.error {
  color: #ff4d4f;
}

.thinking-block {
  margin-top: 12px;
}

.thinking-label {
  font-size: 13px;
  color: #999;
  margin-bottom: 8px;
}

.thinking-content {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 14px;
  font-size: 12px;
  color: #ccc;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
  font-family: 'Courier New', monospace;
}

/* ==== Responsive ==== */
@media (max-width: 900px) {
  .status-cards {
    grid-template-columns: repeat(2, 1fr);
  }
  .main-content {
    grid-template-columns: 1fr;
  }
}
</style>
