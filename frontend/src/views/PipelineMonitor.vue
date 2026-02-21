<script setup lang="ts">
/**
 * Pipeline Monitor — 四层流水线监控面板
 * =======================================
 * 实时展示 Alpha → Portfolio → Risk → Execution 的数据流
 */
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { NCard, NTag, NButton, NIcon, NStatistic, NSpin, NAlert, NEmpty, NTooltip, useMessage, NSwitch } from 'naive-ui'
import { ShieldCheckmarkOutline, FlashOutline, WarningOutline, CheckmarkCircleOutline, CloseCircleOutline, RefreshOutline } from '@vicons/ionicons5'
import MainLayout from '@/layouts/MainLayout.vue'
import { getPipelineStatus, getPipelineConfig, controlCircuitBreaker } from '@/api/pipeline'
import type { PipelineStatusResponse, PipelineConfigResponse } from '@/api/pipeline'

const message = useMessage()

// State
const loading = ref(true)
const status = ref<PipelineStatusResponse | null>(null)
const config = ref<PipelineConfigResponse | null>(null)
const circuitBreakerLoading = ref(false)

// Auto-refresh
let refreshTimer: ReturnType<typeof setInterval> | null = null

// Computed
const uptimeStr = computed(() => {
  if (!status.value) return '--'
  const s = status.value.uptime_seconds
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return `${h}h ${m}m`
})

const layerIcons: Record<string, any> = {
  Alpha: FlashOutline,
  Portfolio: ShieldCheckmarkOutline,
  Risk: WarningOutline,
  Execution: CheckmarkCircleOutline,
}

const layerColors: Record<string, string> = {
  Alpha: '#a855f7',
  Portfolio: '#3b82f6',
  Risk: '#f59e0b',
  Execution: '#22c55e',
}

const layerGradients: Record<string, string> = {
  Alpha: 'linear-gradient(135deg, #a855f7 0%, #7c3aed 100%)',
  Portfolio: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
  Risk: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
  Execution: 'linear-gradient(135deg, #22c55e 0%, #16a34a 100%)',
}

const layerDescriptions: Record<string, string> = {
  Alpha: '信号产出 — 分析市场数据, 生成交易信号 (Insight)',
  Portfolio: '仓位计算 — 将信号转换为具体的交易目标 (Target)',
  Risk: '风控审批 — 8项检查, 保护资金安全',
  Execution: '订单执行 — 将审批通过的目标提交给交易所',
}

function statusTagType(s: string) {
  if (s === 'active') return 'success'
  if (s === 'error') return 'error'
  if (s === 'idle') return 'warning'
  return 'default'
}

// API
async function fetchStatus() {
  try {
    const [s, c] = await Promise.all([
      getPipelineStatus(),
      getPipelineConfig(),
    ])
    status.value = s
    config.value = c
  } catch (e: any) {
    console.error('Pipeline status fetch failed:', e)
  } finally {
    loading.value = false
  }
}

async function handleCircuitBreaker() {
  if (!status.value) return
  circuitBreakerLoading.value = true
  try {
    const action = status.value.circuit_breaker ? 'reset' : 'trigger'
    const result = await controlCircuitBreaker(action, action === 'trigger' ? '手动触发' : '')
    message.success(result.message)
    await fetchStatus()
  } catch (e: any) {
    message.error('操作失败: ' + (e.message || '未知错误'))
  } finally {
    circuitBreakerLoading.value = false
  }
}

onMounted(() => {
  fetchStatus()
  refreshTimer = setInterval(fetchStatus, 5000) // 5s 刷新
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <MainLayout>
    <div class="pipeline-page">
      <!-- Header -->
      <div class="page-header">
        <div class="header-left">
          <h1 class="page-title">
            <span class="title-icon">⚡</span>
            Pipeline Monitor
          </h1>
          <p class="page-subtitle">LEAN 四层流水线 · 实时监控</p>
        </div>
        <div class="header-actions">
          <NButton 
            quaternary
            circle
            @click="fetchStatus"
            :disabled="loading"
          >
            <template #icon>
              <NIcon :component="RefreshOutline" />
            </template>
          </NButton>
        </div>
      </div>

      <NSpin :show="loading">
        <template v-if="status">
          <!-- Status Bar -->
          <div class="status-bar glass-panel">
            <div class="status-item">
              <span class="status-label">状态</span>
              <NTag :type="status.is_active ? 'success' : 'warning'" size="small" round>
                {{ status.is_active ? '运行中' : '待机' }}
              </NTag>
            </div>
            <div class="status-divider" />
            <div class="status-item">
              <span class="status-label">运行时间</span>
              <span class="status-value mono">{{ uptimeStr }}</span>
            </div>
            <div class="status-divider" />
            <div class="status-item">
              <span class="status-label">已处理 TICK</span>
              <span class="status-value mono">{{ (status.stats?.ticks_processed || 0).toLocaleString() }}</span>
            </div>
            <div class="status-divider" />
            <div class="status-item">
              <span class="status-label">已执行订单</span>
              <span class="status-value mono text-green">{{ status.stats?.orders_executed || 0 }}</span>
            </div>
            <div class="status-divider" />
            <div class="status-item circuit-breaker-item">
              <span class="status-label">风控熔断</span>
              <NButton
                :type="status.circuit_breaker ? 'error' : 'default'"
                size="small"
                :loading="circuitBreakerLoading"
                @click="handleCircuitBreaker"
                round
              >
                {{ status.circuit_breaker ? '🚨 已熔断 · 解除' : '正常' }}
              </NButton>
            </div>
          </div>

          <!-- 4-Layer Pipeline Flow -->
          <div class="pipeline-flow">
            <div class="flow-title">
              <span class="flow-label">数据流水线</span>
              <span class="flow-desc">TICK → Insight → Target → Verdict → Order</span>
            </div>
            
            <div class="layers-container">
              <template v-for="(layer, idx) in status.layers" :key="layer.name">
                <!-- Layer Card -->
                <div 
                  class="layer-card glass-panel"
                  :class="{ active: layer.status === 'active', error: layer.status === 'error' }"
                >
                  <div class="layer-header">
                    <div 
                      class="layer-icon-wrapper"
                      :style="{ background: layerGradients[layer.name] }"
                    >
                      <NIcon size="20" color="#fff" :component="layerIcons[layer.name]" />
                    </div>
                    <div class="layer-info">
                      <h3 class="layer-name">{{ layer.name }}</h3>
                      <NTag :type="statusTagType(layer.status)" size="tiny" round>
                        {{ layer.status }}
                      </NTag>
                    </div>
                  </div>
                  
                  <p class="layer-desc">{{ layerDescriptions[layer.name] }}</p>
                  
                  <div class="layer-stats">
                    <div class="stat-row">
                      <span class="stat-label">处理次数</span>
                      <span class="stat-value mono" :style="{ color: layerColors[layer.name] }">
                        {{ layer.count.toLocaleString() }}
                      </span>
                    </div>
                    <div class="stat-row detail-row">
                      <span class="stat-detail">{{ layer.detail || '--' }}</span>
                    </div>
                  </div>
                  
                  <!-- Pulse animation for active layers -->
                  <div v-if="layer.status === 'active'" class="active-pulse" :style="{ borderColor: layerColors[layer.name] }" />
                </div>
                
                <!-- Arrow between layers -->
                <div 
                  v-if="idx < status.layers.length - 1" 
                  class="flow-arrow"
                  :class="{ active: layer.status === 'active' }"
                >
                  <svg width="40" height="24" viewBox="0 0 40 24">
                    <defs>
                      <linearGradient :id="'arrow-grad-' + idx" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" :stop-color="layerColors[layer.name]" stop-opacity="0.6" />
                        <stop offset="100%" :stop-color="layerColors[status.layers[idx + 1]?.name ?? '']" stop-opacity="0.6" />
                      </linearGradient>
                    </defs>
                    <path d="M0 12 L30 12 M25 6 L32 12 L25 18" 
                      :stroke="'url(#arrow-grad-' + idx + ')'" 
                      stroke-width="2" 
                      fill="none" 
                      stroke-linecap="round" 
                      stroke-linejoin="round"
                    />
                  </svg>
                </div>
              </template>
            </div>
          </div>

          <!-- Stats Grid -->
          <div class="stats-grid">
            <div class="stat-card glass-panel">
              <NStatistic label="Insights 产出" :value="status.stats?.insights_generated || 0" />
              <div class="stat-icon" style="color: #a855f7">📡</div>
            </div>
            <div class="stat-card glass-panel">
              <NStatistic label="Targets 创建" :value="status.stats?.targets_created || 0" />
              <div class="stat-icon" style="color: #3b82f6">🎯</div>
            </div>
            <div class="stat-card glass-panel">
              <NStatistic label="风控通过" :value="status.stats?.risk_approved || 0" />
              <div class="stat-icon" style="color: #22c55e">✅</div>
            </div>
            <div class="stat-card glass-panel">
              <NStatistic label="风控拒绝" :value="status.stats?.risk_rejected || 0" />
              <div class="stat-icon" style="color: #ef4444">❌</div>
            </div>
            <div class="stat-card glass-panel">
              <NStatistic label="执行成功" :value="status.stats?.orders_executed || 0" />
              <div class="stat-icon" style="color: #22c55e">📦</div>
            </div>
            <div class="stat-card glass-panel">
              <NStatistic label="错误" :value="status.stats?.errors || 0" />
              <div class="stat-icon" style="color: #f59e0b">⚠️</div>
            </div>
          </div>

          <!-- Config Panel -->
          <div v-if="config" class="config-panel glass-panel">
            <h3 class="section-title">当前配置</h3>
            <div class="config-grid">
              <div class="config-item">
                <span class="config-label">仓位模型</span>
                <NTag type="info" size="small">{{ config.portfolio_model === 'kelly' ? 'Kelly 凯利公式' : '固定比例' }}</NTag>
              </div>
              <div class="config-item">
                <span class="config-label">仓位比例</span>
                <span class="config-value mono">{{ config.risk_percent }}%</span>
              </div>
              <div class="config-item">
                <span class="config-label">默认杠杆</span>
                <span class="config-value mono">{{ config.default_leverage }}x</span>
              </div>
              <div class="config-item">
                <span class="config-label">最大杠杆</span>
                <span class="config-value mono">{{ config.max_leverage }}x</span>
              </div>
              <div class="config-item">
                <span class="config-label">最大持仓</span>
                <span class="config-value mono">{{ config.max_positions }}</span>
              </div>
              <div class="config-item">
                <span class="config-label">日亏损限额</span>
                <span class="config-value mono text-red">{{ config.max_daily_loss_pct }}%</span>
              </div>
              <div class="config-item">
                <span class="config-label">最大敞口</span>
                <span class="config-value mono">{{ config.max_total_exposure_pct }}%</span>
              </div>
              <div class="config-item">
                <span class="config-label">黑名单</span>
                <span class="config-value">{{ config.blacklist.length > 0 ? config.blacklist.join(', ') : '无' }}</span>
              </div>
            </div>
          </div>

          <!-- Recent Activity -->
          <div class="activity-section">
            <div class="activity-panel glass-panel">
              <h3 class="section-title">最近信号 <NTag size="tiny" round>Insights</NTag></h3>
              <div v-if="status.recent_insights.length === 0" class="empty-state">
                <NEmpty description="暂无信号记录" size="small" />
              </div>
              <div v-else class="activity-list">
                <div 
                  v-for="(insight, i) in status.recent_insights.slice(0, 10)" 
                  :key="i"
                  class="activity-item"
                >
                  <span class="activity-dir" :class="insight.direction === 'up' ? 'up' : 'down'">
                    {{ insight.direction === 'up' ? '📈' : '📉' }}
                  </span>
                  <span class="activity-symbol mono">{{ insight.symbol }}</span>
                  <span class="activity-conf mono">
                    {{ (Number(insight.confidence) * 100).toFixed(0) }}%
                  </span>
                  <span class="activity-source">{{ insight.source }}</span>
                  <span class="activity-time">{{ String(insight.timestamp).slice(11, 19) }}</span>
                </div>
              </div>
            </div>

            <div class="activity-panel glass-panel">
              <h3 class="section-title">风控决策 <NTag size="tiny" round>Verdicts</NTag></h3>
              <div v-if="status.recent_verdicts.length === 0" class="empty-state">
                <NEmpty description="暂无风控记录" size="small" />
              </div>
              <div v-else class="activity-list">
                <div 
                  v-for="(verdict, i) in status.recent_verdicts.slice(0, 10)" 
                  :key="i"
                  class="activity-item"
                >
                  <span class="activity-dir">
                    {{ verdict.approved ? '✅' : '❌' }}
                  </span>
                  <span class="activity-symbol mono">{{ verdict.symbol }}</span>
                  <span class="activity-reason">{{ verdict.reason || 'Approved' }}</span>
                  <span class="activity-time">{{ String(verdict.timestamp).slice(11, 19) }}</span>
                </div>
              </div>
            </div>
          </div>
        </template>
      </NSpin>
    </div>
  </MainLayout>
</template>

<style scoped>
.pipeline-page {
  max-width: 1200px;
  margin: 0 auto;
}

/* Header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}
.page-title {
  font-size: 1.8rem;
  font-weight: 800;
  background: linear-gradient(135deg, #fff 0%, #a1a1aa 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  display: flex;
  align-items: center;
  gap: 10px;
}
.title-icon {
  -webkit-text-fill-color: initial;
}
.page-subtitle {
  color: #71717a;
  font-size: 0.85rem;
  margin-top: 4px;
}

/* Status Bar */
.status-bar {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 16px 24px;
  border-radius: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}
.status-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.status-label {
  font-size: 0.7rem;
  color: #71717a;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 600;
}
.status-value {
  font-size: 1rem;
  font-weight: 700;
  color: #fff;
}
.status-divider {
  width: 1px;
  height: 32px;
  background: rgba(255, 255, 255, 0.08);
}
.mono {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}
.text-green { color: #22c55e; }
.text-red { color: #ef4444; }

/* Pipeline Flow */
.pipeline-flow {
  margin-bottom: 24px;
}
.flow-title {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.flow-label {
  font-size: 1rem;
  font-weight: 700;
  color: #fff;
}
.flow-desc {
  font-size: 0.75rem;
  color: #52525b;
  font-family: 'JetBrains Mono', monospace;
}

.layers-container {
  display: flex;
  align-items: stretch;
  gap: 0;
}

.layer-card {
  flex: 1;
  padding: 20px;
  border-radius: 16px;
  position: relative;
  overflow: hidden;
  transition: all 0.3s ease;
  min-width: 0;
}
.layer-card:hover {
  transform: translateY(-2px);
  border-color: rgba(255, 255, 255, 0.12);
}
.layer-card.active {
  border-color: rgba(255, 255, 255, 0.1);
}
.layer-card.error {
  border-color: rgba(239, 68, 68, 0.3);
  box-shadow: 0 0 20px rgba(239, 68, 68, 0.1);
}

.layer-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.layer-icon-wrapper {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.layer-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.layer-name {
  font-size: 0.95rem;
  font-weight: 700;
  color: #fff;
}
.layer-desc {
  font-size: 0.72rem;
  color: #71717a;
  line-height: 1.4;
  margin-bottom: 12px;
}
.layer-stats {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.stat-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.stat-label {
  font-size: 0.72rem;
  color: #a1a1aa;
}
.stat-value {
  font-size: 1.1rem;
  font-weight: 800;
}
.detail-row {
  margin-top: 2px;
}
.stat-detail {
  font-size: 0.68rem;
  color: #52525b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.active-pulse {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  border: 1px solid;
  border-radius: 16px;
  animation: pulse-border 2s ease-in-out infinite;
  pointer-events: none;
  opacity: 0.3;
}

@keyframes pulse-border {
  0%, 100% { opacity: 0.1; }
  50% { opacity: 0.4; }
}

/* Flow Arrow */
.flow-arrow {
  display: flex;
  align-items: center;
  opacity: 0.3;
  flex-shrink: 0;
  transition: opacity 0.3s;
}
.flow-arrow.active {
  opacity: 0.7;
}

/* Stats Grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}
.stat-card {
  padding: 16px;
  border-radius: 12px;
  position: relative;
}
.stat-icon {
  position: absolute;
  top: 12px;
  right: 12px;
  font-size: 1.2rem;
}

/* Config Panel */
.config-panel {
  padding: 20px 24px;
  border-radius: 16px;
  margin-bottom: 24px;
}
.section-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #fff;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.config-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.config-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.config-label {
  font-size: 0.72rem;
  color: #71717a;
  font-weight: 600;
}
.config-value {
  font-size: 0.9rem;
  font-weight: 700;
  color: #fff;
}

/* Activity Section */
.activity-section {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.activity-panel {
  padding: 20px;
  border-radius: 16px;
}
.activity-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.activity-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
  font-size: 0.78rem;
}
.activity-symbol {
  font-weight: 700;
  color: #fff;
  min-width: 80px;
}
.activity-conf {
  color: #a855f7;
  font-weight: 600;
}
.activity-source {
  color: #71717a;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.activity-reason {
  color: #71717a;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.72rem;
}
.activity-time {
  color: #52525b;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
}
.empty-state {
  padding: 24px;
  text-align: center;
}

/* Responsive */
@media (max-width: 768px) {
  .layers-container {
    flex-direction: column;
    gap: 12px;
  }
  .flow-arrow {
    transform: rotate(90deg);
    justify-content: center;
  }
  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
  }
  .config-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .activity-section {
    grid-template-columns: 1fr;
  }
  .status-bar {
    gap: 12px;
  }
  .status-divider {
    display: none;
  }
}
</style>
