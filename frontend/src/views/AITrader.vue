<script setup lang="ts">
/**
 * AITrader.vue
 * ==============
 * AI 自主交易机器人监控面板
 * 
 * 功能:
 * - 启动/停止 AI Trader
 * - 实时状态展示
 * - 决策历史时间线 (含完整思维链)
 * - 配置管理
 * - 手动触发决策
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import MainLayout from '@/layouts/MainLayout.vue'
import {
  getStatus,
  start,
  stop,
  runOnce,
  getDecisions,
  getConfig,
  updateConfig,
  type AITraderStatus,
  type AITraderConfig,
  type Decision,
} from '@/api/aiTrader'

// ==================== State ====================

const status = ref<AITraderStatus | null>(null)
const decisions = ref<Decision[]>([])
const config = ref<AITraderConfig>({
  enabled: false,
  symbols: ['BTCUSDT', 'ETHUSDT'],
  interval: '15m',
  max_position_pct: 30,
  max_leverage: 20,
  min_confidence: 0.6,
})
const loading = ref(false)
const actionLoading = ref(false)
const expandedId = ref<number | null>(null)
const showConfig = ref(false)
const pollTimer = ref<ReturnType<typeof setInterval> | null>(null)

// ==================== Computed ====================

const isRunning = computed(() => status.value?.running ?? false)
const winRate = computed(() => {
  const executed = decisions.value.filter(d => d.executed)
  if (executed.length === 0) return 0
  // 简单统计有 order_id 的比例
  return Math.round((executed.length / decisions.value.length) * 100)
})

const actionLabels: Record<string, { text: string; class: string }> = {
  hold: { text: '📊 观望', class: 'action-hold' },
  open_long: { text: '🟢 做多', class: 'action-long' },
  open_short: { text: '🔴 做空', class: 'action-short' },
  close: { text: '🔒 平仓', class: 'action-close' },
  add_position: { text: '➕ 加仓', class: 'action-add' },
}

const intervalOptions = [
  { label: '5 分钟', value: '5m' },
  { label: '15 分钟', value: '15m' },
  { label: '30 分钟', value: '30m' },
  { label: '1 小时', value: '1h' },
  { label: '4 小时', value: '4h' },
]

// ==================== Actions ====================

async function loadStatus() {
  try {
    const res = await getStatus()
    status.value = res.data
    if (res.data.config) {
      config.value = res.data.config
    }
  } catch (e) {
    console.error('Load status failed:', e)
  }
}

async function loadDecisions() {
  try {
    const res = await getDecisions({ size: 50 })
    decisions.value = res.data
  } catch (e) {
    console.error('Load decisions failed:', e)
  }
}

async function handleStart() {
  actionLoading.value = true
  try {
    await start()
    await loadStatus()
  } finally {
    actionLoading.value = false
  }
}

async function handleStop() {
  actionLoading.value = true
  try {
    await stop()
    await loadStatus()
  } finally {
    actionLoading.value = false
  }
}

async function handleRunOnce() {
  actionLoading.value = true
  try {
    const symbol = config.value.symbols[0] || 'BTCUSDT'
    await runOnce(symbol)
    await loadDecisions()
    await loadStatus()
  } finally {
    actionLoading.value = false
  }
}

async function saveConfig() {
  try {
    await updateConfig(config.value)
    showConfig.value = false
    await loadStatus()
  } catch (e) {
    console.error('Save config failed:', e)
  }
}

function toggleExpand(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}

function formatTime(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatConfidence(c: number) {
  return `${Math.round(c * 100)}%`
}

// ==================== Lifecycle ====================

onMounted(async () => {
  loading.value = true
  await Promise.all([loadStatus(), loadDecisions()])
  loading.value = false
  
  // 轮询状态
  pollTimer.value = setInterval(async () => {
    await loadStatus()
    await loadDecisions()
  }, 30000)
})

onUnmounted(() => {
  if (pollTimer.value) clearInterval(pollTimer.value)
})
</script>

<template>
  <MainLayout>
    <div class="ai-trader-page">
      <!-- Header -->
      <div class="page-header">
        <div class="header-left">
          <h1>🤖 AI 交易员</h1>
          <p class="subtitle">自主分析 · 独立决策 · 持续进化</p>
        </div>
        <div class="header-actions">
          <button
            v-if="!isRunning"
            class="btn btn-start"
            :disabled="actionLoading"
            @click="handleStart"
          >
            ▶ 启动
          </button>
          <button
            v-else
            class="btn btn-stop"
            :disabled="actionLoading"
            @click="handleStop"
          >
            ⏹ 停止
          </button>
          <button
            class="btn btn-secondary"
            :disabled="actionLoading"
            @click="handleRunOnce"
          >
            🔄 手动决策
          </button>
          <button
            class="btn btn-ghost"
            @click="showConfig = !showConfig"
          >
            ⚙️ 配置
          </button>
        </div>
      </div>

      <!-- Status Cards -->
      <div class="status-grid">
        <div class="status-card" :class="{ active: isRunning }">
          <div class="status-icon">{{ isRunning ? '🟢' : '⚪' }}</div>
          <div class="status-info">
            <div class="status-label">运行状态</div>
            <div class="status-value">{{ isRunning ? '运行中' : '已停止' }}</div>
          </div>
        </div>
        <div class="status-card">
          <div class="status-icon">🧠</div>
          <div class="status-info">
            <div class="status-label">总决策</div>
            <div class="status-value">{{ status?.total_decisions ?? 0 }}</div>
          </div>
        </div>
        <div class="status-card">
          <div class="status-icon">⚡</div>
          <div class="status-info">
            <div class="status-label">已执行</div>
            <div class="status-value">{{ status?.total_executed ?? 0 }}</div>
          </div>
        </div>
        <div class="status-card">
          <div class="status-icon">⏰</div>
          <div class="status-info">
            <div class="status-label">最近决策</div>
            <div class="status-value">
              {{ status?.latest_decision_at ? formatTime(status.latest_decision_at) : '—' }}
            </div>
          </div>
        </div>
      </div>

      <!-- Config Panel -->
      <div v-if="showConfig" class="config-panel">
        <h3>⚙️ AI Trader 配置</h3>
        <div class="config-grid">
          <div class="config-item">
            <label>监控交易对</label>
            <input
              v-model="config.symbols[0]"
              placeholder="BTCUSDT"
            />
          </div>
          <div class="config-item">
            <label>决策频率</label>
            <select v-model="config.interval">
              <option v-for="opt in intervalOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>
          <div class="config-item">
            <label>最大仓位 (%)</label>
            <input v-model.number="config.max_position_pct" type="number" min="5" max="80" />
          </div>
          <div class="config-item">
            <label>最大杠杆</label>
            <input v-model.number="config.max_leverage" type="number" min="1" max="125" />
          </div>
          <div class="config-item">
            <label>最低信心</label>
            <input v-model.number="config.min_confidence" type="number" min="0" max="1" step="0.1" />
          </div>
        </div>
        <div class="config-actions">
          <button class="btn btn-primary" @click="saveConfig">💾 保存</button>
          <button class="btn btn-ghost" @click="showConfig = false">取消</button>
        </div>
      </div>

      <!-- Decision Timeline -->
      <div class="section-header">
        <h2>📋 决策时间线</h2>
        <span class="section-hint">点击展开查看 AI 完整思维链</span>
      </div>

      <div v-if="loading" class="loading-state">
        加载中...
      </div>

      <div v-else-if="decisions.length === 0" class="empty-state">
        <div class="empty-icon">🤖</div>
        <p>还没有决策记录</p>
        <p class="hint">启动 AI Trader 或点击"手动决策"开始</p>
      </div>

      <div v-else class="timeline">
        <div
          v-for="d in decisions"
          :key="d.id"
          class="decision-card"
          :class="[
            actionLabels[d.action]?.class || '',
            { expanded: expandedId === d.id }
          ]"
          @click="toggleExpand(d.id)"
        >
          <!-- Card Header -->
          <div class="decision-header">
            <div class="decision-left">
              <span class="decision-action">
                {{ actionLabels[d.action]?.text || d.action }}
              </span>
              <span class="decision-symbol">{{ d.symbol }}</span>
              <span
                class="decision-confidence"
                :class="{
                  high: d.confidence >= 0.7,
                  medium: d.confidence >= 0.4 && d.confidence < 0.7,
                  low: d.confidence < 0.4,
                }"
              >
                {{ formatConfidence(d.confidence) }}
              </span>
            </div>
            <div class="decision-right">
              <span v-if="d.executed" class="badge executed">✅ 已执行</span>
              <span v-else-if="d.reject_reason" class="badge rejected">⏸ {{ d.reject_reason.slice(0, 20) }}</span>
              <span class="decision-time">{{ formatTime(d.created_at) }}</span>
            </div>
          </div>

          <!-- Reasoning Preview -->
          <div class="decision-reasoning-preview">
            {{ d.reasoning.slice(0, 120) }}{{ d.reasoning.length > 120 ? '...' : '' }}
          </div>

          <!-- Expanded Detail -->
          <div v-if="expandedId === d.id" class="decision-detail" @click.stop>
            <!-- 完整思维链 -->
            <div class="detail-section">
              <h4>🧠 AI 思维过程</h4>
              <div class="reasoning-full">{{ d.reasoning }}</div>
            </div>

            <!-- 市场快照 -->
            <div v-if="d.market_snapshot" class="detail-section">
              <h4>📊 市场数据快照</h4>
              <div class="snapshot-grid">
                <div class="snapshot-item">
                  <span class="snapshot-label">价格</span>
                  <span class="snapshot-value">${{ d.market_snapshot.price?.toLocaleString() }}</span>
                </div>
                <div class="snapshot-item">
                  <span class="snapshot-label">24h涨跌</span>
                  <span class="snapshot-value" :class="{ profit: (d.market_snapshot.change_24h || 0) > 0, loss: (d.market_snapshot.change_24h || 0) < 0 }">
                    {{ (d.market_snapshot.change_24h || 0) > 0 ? '+' : '' }}{{ d.market_snapshot.change_24h?.toFixed(2) }}%
                  </span>
                </div>
                <div v-if="d.market_snapshot.rsi" class="snapshot-item">
                  <span class="snapshot-label">RSI</span>
                  <span class="snapshot-value">{{ typeof d.market_snapshot.rsi === 'number' ? d.market_snapshot.rsi.toFixed(1) : d.market_snapshot.rsi }}</span>
                </div>
                <div v-if="d.market_snapshot.atr" class="snapshot-item">
                  <span class="snapshot-label">ATR</span>
                  <span class="snapshot-value">{{ d.market_snapshot.atr }}</span>
                </div>
              </div>
            </div>

            <!-- 交易参数 -->
            <div v-if="d.risk_params" class="detail-section">
              <h4>📐 交易参数</h4>
              <div class="snapshot-grid">
                <div class="snapshot-item">
                  <span class="snapshot-label">仓位</span>
                  <span class="snapshot-value">{{ d.risk_params.position_pct }}%</span>
                </div>
                <div class="snapshot-item">
                  <span class="snapshot-label">杠杆</span>
                  <span class="snapshot-value">{{ d.risk_params.leverage }}x</span>
                </div>
                <div class="snapshot-item">
                  <span class="snapshot-label">止损</span>
                  <span class="snapshot-value">{{ d.risk_params.stop_loss_pct }}%</span>
                </div>
                <div class="snapshot-item">
                  <span class="snapshot-label">止盈</span>
                  <span class="snapshot-value">{{ d.risk_params.take_profit_pct }}%</span>
                </div>
              </div>
              <div v-if="d.risk_params.sl_reason" class="param-reason">
                <strong>止损理由:</strong> {{ d.risk_params.sl_reason }}
              </div>
              <div v-if="d.risk_params.tp_reason" class="param-reason">
                <strong>止盈理由:</strong> {{ d.risk_params.tp_reason }}
              </div>
            </div>

            <!-- 参考的经验 -->
            <div v-if="d.experience_used?.memories?.length" class="detail-section">
              <h4>📚 参考的历史经验</h4>
              <ul class="experience-list">
                <li v-for="(m, i) in d.experience_used.memories" :key="i">{{ m }}</li>
              </ul>
            </div>

            <!-- 账户快照 -->
            <div v-if="d.account_snapshot" class="detail-section">
              <h4>💰 账户状态</h4>
              <div class="snapshot-grid">
                <div class="snapshot-item">
                  <span class="snapshot-label">余额</span>
                  <span class="snapshot-value">${{ d.account_snapshot.balance?.toFixed(2) }}</span>
                </div>
                <div class="snapshot-item">
                  <span class="snapshot-label">今日交易</span>
                  <span class="snapshot-value">{{ d.account_snapshot.today_trades }} 笔</span>
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
.ai-trader-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px 16px;
}

/* Header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 16px;
}

.page-header h1 {
  font-size: 1.8em;
  margin: 0;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  color: #666;
  margin: 4px 0 0;
  font-size: 0.9em;
}

.header-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* Buttons */
.btn {
  padding: 8px 16px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-size: 0.9em;
  font-weight: 500;
  transition: all 0.2s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-start {
  background: linear-gradient(135deg, #10b981, #059669);
  color: white;
}
.btn-start:hover:not(:disabled) { transform: scale(1.02); box-shadow: 0 4px 12px rgba(16,185,129,0.3); }

.btn-stop {
  background: linear-gradient(135deg, #ef4444, #dc2626);
  color: white;
}
.btn-stop:hover:not(:disabled) { transform: scale(1.02); box-shadow: 0 4px 12px rgba(239,68,68,0.3); }

.btn-secondary {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
  border: 1px solid rgba(59, 130, 246, 0.3);
}
.btn-secondary:hover:not(:disabled) { background: rgba(59, 130, 246, 0.2); }

.btn-primary {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: white;
}

.btn-ghost {
  background: transparent;
  color: #888;
  border: 1px solid #333;
}
.btn-ghost:hover { background: rgba(255,255,255,0.05); }

/* Status Grid */
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}

.status-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  transition: all 0.3s;
}

.status-card.active {
  border-color: rgba(16, 185, 129, 0.3);
  background: rgba(16, 185, 129, 0.05);
}

.status-icon { font-size: 1.8em; }
.status-label { font-size: 0.8em; color: #888; }
.status-value { font-size: 1.2em; font-weight: 600; color: #e0e0e0; }

/* Config Panel */
.config-panel {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 24px;
  animation: slideDown 0.2s ease;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.config-panel h3 { margin: 0 0 16px; color: #e0e0e0; }

.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.config-item label {
  display: block;
  font-size: 0.8em;
  color: #888;
  margin-bottom: 4px;
}

.config-item input,
.config-item select {
  width: 100%;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 8px;
  color: #e0e0e0;
  font-size: 0.9em;
  box-sizing: border-box;
}

.config-actions {
  display: flex;
  gap: 8px;
}

/* Section */
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-header h2 {
  margin: 0;
  font-size: 1.3em;
  color: #e0e0e0;
}

.section-hint {
  font-size: 0.8em;
  color: #666;
}

/* Loading / Empty */
.loading-state,
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #888;
}

.empty-icon { font-size: 3em; margin-bottom: 12px; }
.empty-state .hint { font-size: 0.85em; color: #555; }

/* Timeline */
.timeline {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Decision Card */
.decision-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s;
  border-left: 3px solid transparent;
}

.decision-card:hover {
  background: rgba(255, 255, 255, 0.05);
  transform: translateX(2px);
}

.decision-card.expanded {
  background: rgba(255, 255, 255, 0.05);
}

/* Action colors */
.decision-card.action-long { border-left-color: #10b981; }
.decision-card.action-short { border-left-color: #ef4444; }
.decision-card.action-close { border-left-color: #f59e0b; }
.decision-card.action-add { border-left-color: #3b82f6; }
.decision-card.action-hold { border-left-color: #666; }

.decision-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
  gap: 8px;
}

.decision-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.decision-action {
  font-weight: 600;
  font-size: 0.95em;
}

.decision-symbol {
  font-size: 0.8em;
  color: #888;
  background: rgba(255,255,255,0.05);
  padding: 2px 8px;
  border-radius: 4px;
}

.decision-confidence {
  font-size: 0.8em;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
}
.decision-confidence.high { color: #10b981; background: rgba(16,185,129,0.1); }
.decision-confidence.medium { color: #f59e0b; background: rgba(245,158,11,0.1); }
.decision-confidence.low { color: #888; background: rgba(255,255,255,0.05); }

.decision-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.badge {
  font-size: 0.75em;
  padding: 2px 8px;
  border-radius: 4px;
}
.badge.executed { color: #10b981; background: rgba(16,185,129,0.1); }
.badge.rejected { color: #888; background: rgba(255,255,255,0.05); }

.decision-time {
  font-size: 0.8em;
  color: #666;
}

.decision-reasoning-preview {
  font-size: 0.85em;
  color: #999;
  line-height: 1.5;
}

/* Expanded Detail */
.decision-detail {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  animation: slideDown 0.2s ease;
}

.detail-section {
  margin-bottom: 16px;
}

.detail-section h4 {
  margin: 0 0 8px;
  font-size: 0.9em;
  color: #aaa;
}

.reasoning-full {
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
  padding: 12px;
  font-size: 0.88em;
  line-height: 1.7;
  color: #ccc;
  white-space: pre-wrap;
}

.snapshot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
}

.snapshot-item {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  padding: 8px 12px;
}

.snapshot-label {
  display: block;
  font-size: 0.75em;
  color: #888;
}

.snapshot-value {
  font-size: 0.95em;
  font-weight: 600;
  color: #e0e0e0;
}

.snapshot-value.profit { color: #10b981; }
.snapshot-value.loss { color: #ef4444; }

.param-reason {
  margin-top: 8px;
  font-size: 0.85em;
  color: #999;
  padding: 6px 12px;
  background: rgba(0, 0, 0, 0.15);
  border-radius: 6px;
}

.experience-list {
  margin: 0;
  padding-left: 18px;
  font-size: 0.85em;
  color: #999;
  line-height: 1.8;
}

/* Responsive */
@media (max-width: 600px) {
  .page-header { flex-direction: column; }
  .status-grid { grid-template-columns: repeat(2, 1fr); }
  .config-grid { grid-template-columns: 1fr 1fr; }
}
</style>
