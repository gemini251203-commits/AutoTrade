<script setup lang="ts">
/**
 * StrategyManager.vue
 * ====================
 * 量化策略管理界面
 * 
 * 功能:
 * - 策略列表 (CRUD)
 * - 从模板创建
 * - 启动/停止自动交易
 * - 执行日志查看
 * - 交易记忆查看
 */
import { ref, computed, onMounted } from 'vue'
import { NIcon, NSpin, NModal, NInput, NSelect, NSlider, NInputNumber } from 'naive-ui'
import {
  AddOutline,
  PlayOutline,
  StopOutline,
  TrashOutline,
  CreateOutline,
  TimeOutline,
  TrophyOutline,
  DocumentTextOutline,
  ChevronDownOutline,
  CloseOutline,
  BulbOutline,
} from '@vicons/ionicons5'
import MainLayout from '@/layouts/MainLayout.vue'
import {
  listStrategies,
  createStrategy,
  updateStrategy,
  deleteStrategy,
  startStrategy,
  stopStrategy,
  getStrategyLogs,
  getTemplates,
  getMemories,
  deleteMemory,
  type StrategyResponse,
  type StrategyLogResponse,
  type StrategyTemplate,
  type TradeMemoryResponse,
} from '@/api/strategy'
import {
  getPipelineStatus,
  type PipelineStatusResponse,
} from '@/api/pipeline'
import {
  getAutopilotLogs,
  type AutopilotLogResponse,
} from '@/api/chat'
import {
  listTrendSchemes,
  runTrendAnalysis,
  initTrendPresets,
  type TrendSchemeResponse,
} from '@/api/trend'

// ==================== State ====================

const strategies = ref<StrategyResponse[]>([])
const templates = ref<StrategyTemplate[]>([])
const memories = ref<TradeMemoryResponse[]>([])
const loading = ref(false)
const error = ref('')
const pipelineStatus = ref<PipelineStatusResponse | null>(null)
const decisionLogs = ref<AutopilotLogResponse[]>([])
const trendSchemes = ref<TrendSchemeResponse[]>([])
const trendLoading = ref(false)

// Modal state
const showCreateModal = ref(false)
const showLogsModal = ref(false)
const showMemoryModal = ref(false)
const editingStrategy = ref<StrategyResponse | null>(null)
const viewingLogs = ref<StrategyLogResponse[]>([])
const viewingStrategyName = ref('')
const logsLoading = ref(false)

// Wizard state
const wizardStep = ref(1)
const formName = ref('')
const formSymbol = ref('BTCUSDT')
const formInterval = ref('1h')
const formYaml = ref('')
const formSaving = ref(false)

// Module selections
const selectedAlpha = ref('yaml_condition')
const selectedPortfolio = ref('fixed_percent')

// Alpha params
const alphaConfidence = ref(0.5)
const alphaEntryIndicator = ref('rsi')
const alphaEntryCompare = ref('<')
const alphaEntryValue = ref(30)
const alphaExitIndicator = ref('rsi')
const alphaExitCompare = ref('>')
const alphaExitValue = ref(70)

// Portfolio params
const portRiskPercent = ref(10)
const portLeverage = ref(5)
const portSlPct = ref(2.0)
const portTpPct = ref(4.0)
const portKellyFraction = ref(0.5)
const portOddsRatio = ref(2.0)

// Risk params
const riskMaxLeverage = ref(20)
const riskMaxDailyLoss = ref(10)
const riskMaxDailyTrades = ref(20)

const indicatorOptions = [
  { label: 'RSI', value: 'rsi' },
  { label: 'MACD 金叉', value: 'macd_golden_cross' },
  { label: 'MACD 死叉', value: 'macd_death_cross' },
  { label: '均线金叉', value: 'golden_cross' },
  { label: '均线死叉', value: 'death_cross' },
  { label: '成交量比', value: 'volume_ratio' },
  { label: '布林下轨', value: 'bollinger_lower' },
  { label: '收盘价', value: 'close' },
]
const compareOptions = [
  { label: '< 小于', value: '<' },
  { label: '> 大于', value: '>' },
  { label: '== 等于', value: '==' },
  { label: '<= 小于等于', value: '<=' },
  { label: '>= 大于等于', value: '>=' },
]

// Tab state
type TabKey = 'strategies' | 'memories' | 'timeline' | 'trend'
const activeTab = ref<TabKey>('strategies')

// ==================== Computed ====================

const activeCount = computed(() => strategies.value.filter(s => s.is_active).length)
const totalPnl = computed(() => strategies.value.reduce((sum, s) => sum + s.total_pnl, 0))
const totalTrades = computed(() => strategies.value.reduce((sum, s) => sum + s.total_trades, 0))
const totalWins = computed(() => strategies.value.reduce((sum, s) => sum + s.win_trades, 0))
const winRate = computed(() => totalTrades.value > 0 ? ((totalWins.value / totalTrades.value) * 100).toFixed(1) : '0.0')

const intervalOptions = [
  { label: '1分钟', value: '1m' },
  { label: '5分钟', value: '5m' },
  { label: '15分钟', value: '15m' },
  { label: '30分钟', value: '30m' },
  { label: '1小时', value: '1h' },
  { label: '4小时', value: '4h' },
  { label: '1天', value: '1d' },
]

// ==================== Methods ====================

async function fetchAll() {
  loading.value = true
  error.value = ''
  try {
    const [strats, tmps] = await Promise.all([
      listStrategies(),
      getTemplates(),
    ])
    strategies.value = strats
    templates.value = tmps
  } catch (e: any) {
    error.value = e.response?.data?.detail || '加载失败'
  } finally {
    loading.value = false
  }
}

function openCreateModal(template?: StrategyTemplate) {
  editingStrategy.value = null
  wizardStep.value = 1
  formName.value = template?.name || ''
  formSymbol.value = 'BTCUSDT'
  formInterval.value = '1h'
  formYaml.value = template?.config_yaml || ''
  showCreateModal.value = true
}

function openEditModal(strategy: StrategyResponse) {
  editingStrategy.value = strategy
  formName.value = strategy.name
  formSymbol.value = strategy.symbol
  formInterval.value = strategy.interval
  formYaml.value = strategy.config_yaml
  wizardStep.value = 4  // Jump to review for editing
  showCreateModal.value = true
}

function buildPipelineYaml(): string {
  const lines: string[] = []
  lines.push(`name: "${formName.value}"`)
  lines.push(`symbol: ${formSymbol.value}`)
  lines.push(`interval: ${formInterval.value}`)
  lines.push('alphas:')

  if (selectedAlpha.value === 'yaml_condition') {
    lines.push('  - type: "yaml_condition"')
    lines.push(`    name: "${alphaEntryIndicator.value}信号"`)
    lines.push('    entry:')
    lines.push('      operator: AND')
    lines.push('      conditions:')
    lines.push(`        - indicator: ${alphaEntryIndicator.value}`)
    lines.push(`          compare: "${alphaEntryCompare.value}"`)
    lines.push(`          value: ${alphaEntryValue.value}`)
    lines.push('    exit:')
    lines.push('      operator: OR')
    lines.push('      conditions:')
    lines.push(`        - indicator: ${alphaExitIndicator.value}`)
    lines.push(`          compare: "${alphaExitCompare.value}"`)
    lines.push(`          value: ${alphaExitValue.value}`)
  } else {
    lines.push('  - type: "ai_agent"')
    lines.push('    name: "AI智能研判"')
    lines.push(`    confidence_threshold: ${alphaConfidence.value}`)
  }

  lines.push('portfolio:')
  if (selectedPortfolio.value === 'fixed_percent') {
    lines.push('  type: "fixed_percent"')
    lines.push('  params:')
    lines.push(`    risk_percent: ${portRiskPercent.value}`)
    lines.push(`    default_leverage: ${portLeverage.value}`)
    lines.push(`    default_sl_pct: ${portSlPct.value}`)
    lines.push(`    default_tp_pct: ${portTpPct.value}`)
  } else {
    lines.push('  type: "kelly"')
    lines.push('  params:')
    lines.push(`    kelly_fraction: ${portKellyFraction.value}`)
    lines.push(`    default_leverage: ${portLeverage.value}`)
    lines.push(`    odds_ratio: ${portOddsRatio.value}`)
  }

  lines.push('risk:')
  lines.push('  type: "standard"')
  lines.push('  params:')
  lines.push(`    max_leverage: ${riskMaxLeverage.value}`)
  lines.push(`    max_daily_loss_pct: ${riskMaxDailyLoss.value}`)
  lines.push(`    max_daily_trades: ${riskMaxDailyTrades.value}`)

  lines.push('execution:')
  lines.push('  type: "market"')
  return lines.join('\n')
}

async function handleSave() {
  if (!formName.value || !formSymbol.value) {
    error.value = '请填写策略名称和交易对'
    return
  }
  formSaving.value = true
  try {
    const yaml = editingStrategy.value ? formYaml.value : buildPipelineYaml()
    const data = {
      name: formName.value,
      symbol: formSymbol.value.toUpperCase(),
      interval: formInterval.value,
      config_yaml: yaml,
    }
    if (editingStrategy.value) {
      await updateStrategy(editingStrategy.value.id, data)
    } else {
      await createStrategy(data)
    }
    showCreateModal.value = false
    await fetchAll()
  } catch (e: any) {
    error.value = e.response?.data?.detail || '保存失败'
  } finally {
    formSaving.value = false
  }
}

async function handleDelete(id: number) {
  if (!confirm('确定删除此策略？')) return
  try {
    await deleteStrategy(id)
    await fetchAll()
  } catch (e: any) {
    error.value = e.response?.data?.detail || '删除失败'
  }
}

async function handleToggle(strategy: StrategyResponse) {
  try {
    if (strategy.is_active) {
      await stopStrategy(strategy.id)
    } else {
      await startStrategy(strategy.id)
    }
    await fetchAll()
  } catch (e: any) {
    error.value = e.response?.data?.detail || '操作失败'
  }
}

async function openLogs(strategy: StrategyResponse) {
  viewingStrategyName.value = strategy.name
  logsLoading.value = true
  showLogsModal.value = true
  try {
    viewingLogs.value = await getStrategyLogs(strategy.id, 50)
  } catch {
    viewingLogs.value = []
  } finally {
    logsLoading.value = false
  }
}

async function fetchMemories() {
  try {
    memories.value = await getMemories(undefined, 50)
  } catch {
    memories.value = []
  }
}

async function handleDeleteMemory(id: number) {
  if (!confirm('确定删除这条交易记忆？')) return
  try {
    await deleteMemory(id)
    memories.value = memories.value.filter(m => m.id !== id)
  } catch (e: any) {
    error.value = e.response?.data?.detail || '删除失败'
  }
}

function formatDate(iso: string) {
  const d = new Date(iso)
  return `${d.getMonth()+1}/${d.getDate()} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`
}

function pnlColor(v: number) {
  if (v > 0) return '#22c55e'
  if (v < 0) return '#ef4444'
  return '#6b7280'
}

async function fetchDecisionLogs() {
  try {
    decisionLogs.value = await getAutopilotLogs(20)
  } catch (e) {
    console.warn('Failed to fetch decision logs', e)
  }
}

function decisionColor(d: string) {
  if (d === 'open_long') return '#22c55e'
  if (d === 'open_short') return '#ef4444'
  if (d === 'close_long' || d === 'close_short') return '#f59e0b'
  if (d === 'error') return '#ef4444'
  return '#6b7280'
}

function decisionLabel(d: string) {
  const map: Record<string, string> = {
    hold: '观望', open_long: '做多', open_short: '做空',
    close_long: '平多', close_short: '平空', error: '异常',
  }
  return map[d] || d
}

async function fetchTrendSchemes() {
  trendLoading.value = true
  try {
    trendSchemes.value = await listTrendSchemes()
  } catch (e) {
    console.warn('Failed to fetch trend schemes', e)
  } finally {
    trendLoading.value = false
  }
}

async function handleRunTrend(schemeId: number, symbol: string = 'BTCUSDT') {
  trendLoading.value = true
  try {
    await runTrendAnalysis(schemeId, symbol)
    await fetchTrendSchemes()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '分析失败'
  } finally {
    trendLoading.value = false
  }
}

async function handleInitPresets() {
  try {
    await initTrendPresets()
    await fetchTrendSchemes()
  } catch (e) {
    console.warn('Init presets failed', e)
  }
}

function regimeLabel(r: string) {
  const map: Record<string, string> = {
    trending_up: '📈 上涨趋势', trending_down: '📉 下跌趋势',
    ranging: '⇔ 震荡', volatile: '⚡ 高波动',
    insufficient_data: '⚠️ 数据不足', unknown: '❓ 未分析',
  }
  return map[r] || r
}

function regimeColor(r: string) {
  if (r === 'trending_up') return '#22c55e'
  if (r === 'trending_down') return '#ef4444'
  if (r === 'volatile') return '#f59e0b'
  return '#6b7280'
}

onMounted(() => {
  fetchAll()
  // 加载 Pipeline 状态
  getPipelineStatus().then(s => pipelineStatus.value = s).catch(() => {})
})
</script>

<template>
  <MainLayout>
    <div class="max-w-7xl mx-auto space-y-6">
      <!-- Header -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-white">量化策略</h1>
          <p class="text-sm text-gray-500 mt-1">AI 驱动的自动交易策略管理</p>
        </div>
        <button
          @click="openCreateModal()"
          class="create-btn"
        >
          <NIcon size="18"><AddOutline /></NIcon>
          新建策略
        </button>
      </div>
      
      <!-- Stats -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">运行中</div>
          <div class="stat-value text-green-500">{{ activeCount }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">累计交易</div>
          <div class="stat-value">{{ totalTrades }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">胜率</div>
          <div class="stat-value">{{ winRate }}%</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">累计盈亏</div>
          <div class="stat-value" :style="{ color: pnlColor(totalPnl) }">
            {{ totalPnl >= 0 ? '+' : '' }}{{ totalPnl.toFixed(2) }}
          </div>
        </div>
      </div>

      <!-- Pipeline Status -->
      <div v-if="pipelineStatus" class="pl-panel">
        <div class="pl-header">
          <div class="pl-title-row">
            <span class="pl-dot" :style="{ background: pipelineStatus.circuit_breaker ? '#ef4444' : '#22c55e' }"></span>
            <span class="pl-title">交易流水线</span>
          </div>
          <span class="pl-badge" :class="pipelineStatus.circuit_breaker ? 'pl-badge-danger' : 'pl-badge-ok'">
            {{ pipelineStatus.circuit_breaker ? '熔断中' : '运行正常' }}
          </span>
        </div>
        <div class="pl-flow">
          <template v-for="(layer, idx) in pipelineStatus.layers" :key="layer.name">
            <div class="pl-layer" :class="'pl-layer--' + layer.name.toLowerCase()">
              <div class="pl-layer-icon">
                <span class="pl-layer-dot" :class="layer.status"></span>
              </div>
              <div class="pl-layer-body">
                <span class="pl-layer-name">{{ layer.name }}</span>
                <span class="pl-layer-tag">{{ layer.status }}</span>
              </div>
              <span class="pl-layer-count">{{ layer.count }}</span>
            </div>
            <div v-if="idx < pipelineStatus.layers.length - 1" class="pl-arrow">
              <svg width="20" height="20" viewBox="0 0 20 20"><path d="M7 4L13 10L7 16" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>
            </div>
          </template>
        </div>
      </div>

      <!-- Tabs -->
      <div class="flex gap-1 p-1 rounded-lg" style="background: rgba(255,255,255,0.03);">
        <button
          @click="activeTab = 'strategies'"
          class="px-4 py-2 rounded-md text-sm transition-all"
          :style="{
            background: activeTab === 'strategies' ? 'rgba(138,43,226,0.15)' : 'transparent',
            color: activeTab === 'strategies' ? '#a855f7' : '#6b7280',
          }"
        >
          策略列表
        </button>
        <button
          @click="activeTab = 'memories'; fetchMemories()"
          class="px-4 py-2 rounded-md text-sm transition-all"
          :style="{
            background: activeTab === 'memories' ? 'rgba(138,43,226,0.15)' : 'transparent',
            color: activeTab === 'memories' ? '#a855f7' : '#6b7280',
          }"
        >
          交易记忆
        </button>
        <button
          @click="activeTab = 'timeline'; fetchDecisionLogs()"
          class="px-4 py-2 rounded-md text-sm transition-all"
          :style="{
            background: activeTab === 'timeline' ? 'rgba(138,43,226,0.15)' : 'transparent',
            color: activeTab === 'timeline' ? '#a855f7' : '#6b7280',
          }"
        >
          决策时间线
        </button>
        <button
          @click="activeTab = 'trend'; fetchTrendSchemes()"
          class="px-4 py-2 rounded-md text-sm transition-all"
          :style="{
            background: activeTab === 'trend' ? 'rgba(138,43,226,0.15)' : 'transparent',
            color: activeTab === 'trend' ? '#a855f7' : '#6b7280',
          }"
        >
          趋势分析
        </button>
      </div>

      <!-- Error -->
      <div
        v-if="error"
        class="p-3 rounded-lg text-sm"
        style="background: rgba(220,38,38,0.1); border: 1px solid rgba(220,38,38,0.2); color: #ef4444;"
      >
        {{ error }}
        <button @click="error = ''" class="ml-2 underline">关闭</button>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="flex justify-center py-12">
        <NSpin size="medium" />
      </div>

      <!-- Strategies Tab -->
      <template v-else-if="activeTab === 'strategies'">
        <!-- Strategy Templates (quick create) -->
        <div v-if="templates.length > 0">
          <h3 class="text-sm font-medium text-gray-400 mb-3">快速创建 (模板)</h3>
          <div class="grid grid-cols-5 gap-3">
            <button
              v-for="tmpl in templates"
              :key="tmpl.name"
              @click="openCreateModal(tmpl)"
              class="template-card"
            >
            <div class="text-sm text-white font-medium truncate">{{ tmpl.name }}</div>
              <div class="text-xs text-gray-500 mt-1 line-clamp-2">{{ tmpl.symbol }} · {{ tmpl.interval }}</div>
              <div v-if="tmpl.modules" class="text-[10px] text-purple-400 mt-1 truncate opacity-70">{{ tmpl.modules }}</div>
            </button>
          </div>
        </div>

        <!-- Strategy List -->
        <div v-if="strategies.length === 0 && !loading" class="text-center py-16">
          <NIcon size="48" style="color: #374151;"><DocumentTextOutline /></NIcon>
          <p class="text-gray-500 mt-4">暂无策略，点击上方按钮创建</p>
        </div>

        <div v-else class="space-y-3">
          <div
            v-for="s in strategies"
            :key="s.id"
            class="strategy-card"
          >
            <div class="flex items-center justify-between">
              <!-- Left: Info -->
              <div class="flex items-center gap-4 flex-1 min-w-0">
                <!-- Status dot -->
                <div class="relative flex-shrink-0">
                  <span
                    v-if="s.is_active"
                    class="absolute inline-flex h-3 w-3 rounded-full opacity-50 animate-ping"
                    style="background: #22c55e;"
                  ></span>
                  <span
                    class="relative inline-flex h-3 w-3 rounded-full"
                    :style="{ background: s.is_active ? '#22c55e' : '#374151' }"
                  ></span>
                </div>

                <!-- Name & Symbol -->
                <div class="min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="text-white font-medium truncate">{{ s.name }}</span>
                    <span
                      class="px-2 py-0.5 rounded text-xs font-mono"
                      style="background: rgba(59,130,246,0.1); color: #3b82f6;"
                    >
                      {{ s.symbol }}
                    </span>
                    <span class="text-xs text-gray-600 font-mono">{{ s.interval }}</span>
                    <span
                      v-if="s.strategy_type === 'pipeline'"
                      class="px-2 py-0.5 rounded text-[10px] font-medium tracking-wide flex items-center gap-1"
                      style="background: rgba(168,85,247,0.1); color: #a855f7; border: 1px solid rgba(168,85,247,0.2);"
                    >
                      <NIcon size="12"><TrophyOutline /></NIcon> PIPELINE
                    </span>
                  </div>
                  <div class="flex items-center gap-4 mt-1 text-xs text-gray-500">
                    <span>交易: {{ s.total_trades }}</span>
                    <span>胜: {{ s.win_trades }}</span>
                    <span :style="{ color: pnlColor(s.total_pnl) }">
                      PnL: {{ s.total_pnl >= 0 ? '+' : '' }}{{ s.total_pnl.toFixed(2) }}
                    </span>
                    <span v-if="s.last_run_at">
                      <NIcon size="12"><TimeOutline /></NIcon>
                      {{ formatDate(s.last_run_at) }}
                    </span>
                  </div>
                </div>
              </div>
              
              <!-- Right: Actions -->
              <div class="flex items-center gap-2 flex-shrink-0">
                <!-- Logs -->
                <button
                  @click="openLogs(s)"
                  class="w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
                  style="color: #6b7280;"
                  title="查看日志"
                >
                  <NIcon size="16"><DocumentTextOutline /></NIcon>
                </button>
                <!-- Edit -->
                <button
                  @click="openEditModal(s)"
                  class="w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
                  style="color: #6b7280;"
                  title="编辑"
                  :disabled="s.is_active"
                >
                  <NIcon size="16"><CreateOutline /></NIcon>
                </button>
                <!-- Toggle -->
                <button
                  @click="handleToggle(s)"
                  class="px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1 transition-all"
                  :style="{
                    background: s.is_active ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
                    color: s.is_active ? '#ef4444' : '#22c55e',
                    border: `1px solid ${s.is_active ? 'rgba(239,68,68,0.2)' : 'rgba(34,197,94,0.2)'}`,
                  }"
                >
                  <NIcon size="14">
                    <component :is="s.is_active ? StopOutline : PlayOutline" />
                  </NIcon>
                  {{ s.is_active ? '停止' : '启动' }}
                </button>
                <!-- Delete -->
                <button
                  @click="handleDelete(s.id)"
                  class="w-8 h-8 rounded-lg flex items-center justify-center transition-colors hover:bg-red-500/10"
                  style="color: #6b7280;"
                  title="删除"
                  :disabled="s.is_active"
                >
                  <NIcon size="16"><TrashOutline /></NIcon>
                </button>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Memories Tab -->
      <template v-else-if="activeTab === 'memories'">
        <div v-if="memories.length === 0" class="text-center py-16">
          <NIcon size="48" style="color: #374151;"><BulbOutline /></NIcon>
          <p class="text-gray-500 mt-4">暂无交易记忆</p>
          <p class="text-gray-600 text-sm mt-1">AI 会在完成交易后自动总结经验</p>
        </div>
        <div v-else class="space-y-3">
          <div
            v-for="m in memories"
            :key="m.id"
            class="memory-card"
          >
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center gap-2">
                <span
                  class="px-2 py-0.5 rounded text-xs font-mono"
                  :style="{
                    background: m.trade_result === 'win' ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
                    color: m.trade_result === 'win' ? '#22c55e' : '#ef4444',
                  }"
                >
                  {{ m.trade_result === 'win' ? 'WIN' : 'LOSS' }}
                </span>
                <span class="text-sm text-white font-mono">{{ m.symbol }}</span>
                <span v-if="m.side" class="px-1.5 py-0.5 rounded text-[10px] font-mono" :style="{
                  background: m.side === 'long' ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
                  color: m.side === 'long' ? '#22c55e' : '#ef4444',
                }">{{ m.side === 'long' ? '做多' : '做空' }}</span>
                <span v-if="m.leverage" class="px-1.5 py-0.5 rounded text-[10px] font-mono" style="background: rgba(139,92,246,0.1); color: #a78bfa;">{{ m.leverage }}x</span>
                <span class="text-xs text-gray-500">{{ m.strategy_name }}</span>
              </div>
              <div class="flex items-center gap-3 text-xs text-gray-500">
                <div class="text-right">
                  <span :style="{ color: pnlColor(m.pnl_pct) }" class="font-mono font-medium">
                    {{ m.pnl_pct >= 0 ? '+' : '' }}{{ m.pnl_pct.toFixed(2) }}%
                  </span>
                  <span v-if="m.pnl_usdt != null" class="block text-[11px] font-mono" :style="{ color: pnlColor(m.pnl_usdt), opacity: 0.8 }">
                    {{ m.pnl_usdt >= 0 ? '+' : '' }}{{ m.pnl_usdt.toFixed(2) }} USDT
                  </span>
                </div>
                <span>{{ formatDate(m.created_at || '') }}</span>
                <button
                  @click.stop="handleDeleteMemory(m.id)"
                  class="ml-1 p-1 rounded hover:bg-red-500/10 transition-colors text-gray-500 hover:text-red-400"
                  title="删除"
                >
                  <NIcon size="14"><TrashOutline /></NIcon>
                </button>
              </div>
            </div>
            <div class="text-sm text-gray-300 mb-1">{{ m.lesson }}</div>
            <div v-if="m.open_reason" class="text-xs text-gray-500">{{ m.open_reason }}</div>
          </div>
        </div>
      </template>

      <!-- Decision Timeline Tab -->
      <template v-else-if="activeTab === 'timeline'">
        <div v-if="decisionLogs.length === 0" class="text-center py-16">
          <p class="text-gray-500 mt-4">暂无决策记录</p>
          <p class="text-gray-600 text-sm mt-1">启动策略自动交易后，AI 的每次决策将显示在此</p>
        </div>
        <div v-else class="tl-list">
          <div
            v-for="log in decisionLogs"
            :key="log.id"
            class="tl-item"
          >
            <div class="tl-dot" :style="{ background: decisionColor(log.decision) }"></div>
            <div class="tl-content">
              <div class="tl-header">
                <span class="tl-badge" :style="{ color: decisionColor(log.decision), borderColor: decisionColor(log.decision) + '40' }">
                  {{ decisionLabel(log.decision) }}
                </span>
                <span class="tl-symbol">{{ log.symbol }}</span>
                <span v-if="log.strategy_name" class="tl-strategy">策略: {{ log.strategy_name }}</span>
                <span class="tl-time">{{ formatDate(log.created_at) }}</span>
              </div>
              <div class="tl-summary">{{ log.summary }}</div>
              <details v-if="log.thinking" class="tl-thinking">
                <summary>查看 AI 思考过程</summary>
                <pre class="tl-pre">{{ log.thinking }}</pre>
              </details>
            </div>
          </div>
        </div>
      </template>

      <!-- Trend Analysis Tab -->
      <template v-else-if="activeTab === 'trend'">
        <div v-if="trendLoading" class="flex justify-center py-12">
          <NSpin size="medium" />
        </div>
        <div v-else-if="trendSchemes.length === 0" class="text-center py-16">
          <p class="text-gray-500 mt-4">暂无趋势分析方案</p>
          <button
            @click="handleInitPresets()"
            class="mt-4 px-4 py-2 rounded-lg text-sm transition-colors"
            style="background: rgba(138,43,226,0.15); color: #a855f7;"
          >
            📦 初始化预置方案
          </button>
        </div>
        <div v-else class="space-y-4">
          <div
            v-for="s in trendSchemes"
            :key="s.id"
            class="trend-card"
          >
            <!-- Header -->
            <div class="flex items-center justify-between mb-3">
              <div class="flex items-center gap-2">
                <span
                  class="w-2 h-2 rounded-full"
                  :style="{ background: s.is_active ? '#22c55e' : '#4b5563' }"
                ></span>
                <span class="text-sm font-medium text-white">{{ s.name }}</span>
                <span v-if="s.is_preset" class="px-1.5 py-0.5 rounded text-[10px]" style="background: rgba(139,92,246,0.1); color: #a78bfa;">预置</span>
              </div>
              <button
                @click="handleRunTrend(s.id)"
                class="px-3 py-1.5 rounded-lg text-xs transition-colors"
                style="background: rgba(138,43,226,0.15); color: #a855f7;"
                :disabled="trendLoading"
              >
                ▶ 运行分析
              </button>
            </div>

            <!-- Result -->
            <div v-if="s.last_result" class="trend-result">
              <div class="trend-regime" :style="{ color: regimeColor(s.last_result.regime) }">
                {{ regimeLabel(s.last_result.regime) }}
              </div>
              <div class="trend-metrics">
                <div class="trend-metric">
                  <span class="trend-metric-label">方向</span>
                  <span class="trend-metric-value" :style="{ color: s.last_result.direction_score > 0 ? '#22c55e' : s.last_result.direction_score < 0 ? '#ef4444' : '#6b7280' }">
                    {{ s.last_result.direction }} ({{ s.last_result.direction_score > 0 ? '+' : '' }}{{ s.last_result.direction_score }})
                  </span>
                </div>
                <div class="trend-metric">
                  <span class="trend-metric-label">强度</span>
                  <span class="trend-metric-value">{{ s.last_result.strength }}</span>
                </div>
                <div class="trend-metric">
                  <span class="trend-metric-label">波动率</span>
                  <span class="trend-metric-value">{{ s.last_result.volatility }}</span>
                </div>
                <div class="trend-metric">
                  <span class="trend-metric-label">动量</span>
                  <span class="trend-metric-value" :style="{ color: s.last_result.momentum_score > 0 ? '#22c55e' : s.last_result.momentum_score < 0 ? '#ef4444' : '#6b7280' }">
                    {{ s.last_result.momentum }}
                  </span>
                </div>
                <div class="trend-metric">
                  <span class="trend-metric-label">置信度</span>
                  <span class="trend-metric-value">{{ s.last_result.confidence }}%</span>
                </div>
              </div>
              <div v-if="s.last_result.suitable_strategies?.length" class="mt-2">
                <span class="text-[10px] text-gray-500">适合策略: </span>
                <span
                  v-for="st in s.last_result.suitable_strategies"
                  :key="st"
                  class="inline-block px-1.5 py-0.5 rounded text-[10px] mr-1 mb-1"
                  style="background: rgba(34,197,94,0.1); color: #22c55e;"
                >{{ st }}</span>
              </div>
              <div class="text-[10px] text-gray-600 mt-1" v-if="s.last_run_at">
                上次分析: {{ formatDate(s.last_run_at) }}
              </div>
            </div>
            <div v-else class="text-xs text-gray-600">尚未运行分析，点击"运行分析"开始</div>
          </div>
        </div>
      </template>
    </div>

    <!-- Create/Edit Modal (4-Step Wizard) -->
    <NModal
      v-model:show="showCreateModal"
      preset="card"
      :title="editingStrategy ? '编辑策略' : '构建策略'"
      style="width: 680px; background: #18181b; border: 1px solid rgba(255,255,255,0.06);"
      :bordered="false"
    >
      <!-- Step indicator -->
      <div v-if="!editingStrategy" class="flex items-center gap-2 mb-6">
        <template v-for="step in 4" :key="step">
          <div
            class="flex items-center gap-2 cursor-pointer"
            @click="wizardStep = step"
          >
            <div
              class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium transition-all"
              :style="{
                background: wizardStep >= step ? 'linear-gradient(135deg, #8a2be2, #5a189a)' : 'rgba(255,255,255,0.05)',
                color: wizardStep >= step ? 'white' : '#6b7280',
              }"
            >{{ step }}</div>
            <span class="text-xs" :style="{ color: wizardStep >= step ? '#a855f7' : '#4b5563' }">
              {{ ['Alpha 信号', 'Portfolio 仓位', 'Risk 风控', '基本信息'][step - 1] }}
            </span>
          </div>
          <div v-if="step < 4" class="flex-1 h-px" style="background: rgba(255,255,255,0.06);"></div>
        </template>
      </div>

      <div class="space-y-4">
        <!-- Step 1: Alpha -->
        <template v-if="wizardStep === 1 && !editingStrategy">
          <div class="text-sm text-gray-300 mb-3">选择信号源模块：AI 根据什么来判断买卖时机？</div>
          <div class="grid grid-cols-2 gap-3">
            <button
              @click="selectedAlpha = 'yaml_condition'"
              class="p-4 rounded-lg text-left transition-all"
              :style="{
                background: selectedAlpha === 'yaml_condition' ? 'rgba(138,43,226,0.15)' : 'rgba(255,255,255,0.03)',
                border: selectedAlpha === 'yaml_condition' ? '1px solid rgba(138,43,226,0.4)' : '1px solid rgba(255,255,255,0.06)',
              }"
            >
              <div class="text-sm text-white font-medium">📊 技术指标条件</div>
              <div class="text-xs text-gray-500 mt-1">RSI, MACD, EMA 等指标组合</div>
            </button>
            <button
              @click="selectedAlpha = 'ai_agent'"
              class="p-4 rounded-lg text-left transition-all"
              :style="{
                background: selectedAlpha === 'ai_agent' ? 'rgba(138,43,226,0.15)' : 'rgba(255,255,255,0.03)',
                border: selectedAlpha === 'ai_agent' ? '1px solid rgba(138,43,226,0.4)' : '1px solid rgba(255,255,255,0.06)',
              }"
            >
              <div class="text-sm text-white font-medium">🤖 AI 智能判断</div>
              <div class="text-xs text-gray-500 mt-1">AI 大模型综合分析行情</div>
            </button>
          </div>
          <!-- Alpha params -->
          <div v-if="selectedAlpha === 'yaml_condition'" class="space-y-3 mt-3 p-3 rounded-lg" style="background: rgba(255,255,255,0.02);">
            <div class="text-xs text-purple-400 mb-2">入场条件</div>
            <div class="grid grid-cols-3 gap-2">
              <NSelect v-model:value="alphaEntryIndicator" :options="indicatorOptions" size="small" />
              <NSelect v-model:value="alphaEntryCompare" :options="compareOptions" size="small" />
              <NInputNumber v-model:value="alphaEntryValue" size="small" />
            </div>
            <div class="text-xs text-purple-400 mt-3 mb-2">出场条件</div>
            <div class="grid grid-cols-3 gap-2">
              <NSelect v-model:value="alphaExitIndicator" :options="indicatorOptions" size="small" />
              <NSelect v-model:value="alphaExitCompare" :options="compareOptions" size="small" />
              <NInputNumber v-model:value="alphaExitValue" size="small" />
            </div>
          </div>
          <div v-else class="p-3 rounded-lg" style="background: rgba(255,255,255,0.02);">
            <label class="text-xs text-gray-500">最低信心阈值</label>
            <NSlider v-model:value="alphaConfidence" :min="0.1" :max="1.0" :step="0.1" :format-tooltip="(v: number) => `${(v * 100).toFixed(0)}%`" class="mt-2" />
          </div>
        </template>

        <!-- Step 2: Portfolio -->
        <template v-if="wizardStep === 2 && !editingStrategy">
          <div class="text-sm text-gray-300 mb-3">选择仓位管理模型：每次用多少资金开仓？</div>
          <div class="grid grid-cols-2 gap-3">
            <button
              @click="selectedPortfolio = 'fixed_percent'"
              class="p-4 rounded-lg text-left transition-all"
              :style="{
                background: selectedPortfolio === 'fixed_percent' ? 'rgba(138,43,226,0.15)' : 'rgba(255,255,255,0.03)',
                border: selectedPortfolio === 'fixed_percent' ? '1px solid rgba(138,43,226,0.4)' : '1px solid rgba(255,255,255,0.06)',
              }"
            >
              <div class="text-sm text-white font-medium">📐 固定比例</div>
              <div class="text-xs text-gray-500 mt-1">每次用余额的固定百分比</div>
            </button>
            <button
              @click="selectedPortfolio = 'kelly'"
              class="p-4 rounded-lg text-left transition-all"
              :style="{
                background: selectedPortfolio === 'kelly' ? 'rgba(138,43,226,0.15)' : 'rgba(255,255,255,0.03)',
                border: selectedPortfolio === 'kelly' ? '1px solid rgba(138,43,226,0.4)' : '1px solid rgba(255,255,255,0.06)',
              }"
            >
              <div class="text-sm text-white font-medium">🎯 凯利公式</div>
              <div class="text-xs text-gray-500 mt-1">基于胜率动态计算最优仓位</div>
            </button>
          </div>
          <div class="space-y-3 mt-3 p-3 rounded-lg" style="background: rgba(255,255,255,0.02);">
            <div class="grid grid-cols-2 gap-3">
              <div v-if="selectedPortfolio === 'fixed_percent'">
                <label class="text-xs text-gray-500">每次仓位 (%)</label>
                <NInputNumber v-model:value="portRiskPercent" :min="1" :max="50" size="small" class="mt-1" />
              </div>
              <div v-else>
                <label class="text-xs text-gray-500">凯利比例</label>
                <NInputNumber v-model:value="portKellyFraction" :min="0.1" :max="1.0" :step="0.1" size="small" class="mt-1" />
              </div>
              <div>
                <label class="text-xs text-gray-500">杠杆倍数</label>
                <NInputNumber v-model:value="portLeverage" :min="1" :max="20" size="small" class="mt-1" />
              </div>
              <div>
                <label class="text-xs text-gray-500">止损 (%)</label>
                <NInputNumber v-model:value="portSlPct" :min="0.5" :max="10" :step="0.5" size="small" class="mt-1" />
              </div>
              <div>
                <label class="text-xs text-gray-500">止盈 (%)</label>
                <NInputNumber v-model:value="portTpPct" :min="1" :max="30" :step="0.5" size="small" class="mt-1" />
              </div>
            </div>
          </div>
        </template>

        <!-- Step 3: Risk -->
        <template v-if="wizardStep === 3 && !editingStrategy">
          <div class="text-sm text-gray-300 mb-3">配置风控参数：设定安全边界</div>
          <div class="p-4 rounded-lg space-y-4" style="background: rgba(255,255,255,0.02);">
            <div>
              <label class="text-xs text-gray-500">最大杠杆</label>
              <NSlider v-model:value="riskMaxLeverage" :min="1" :max="125" :step="1" class="mt-1" />
              <div class="text-right text-xs text-purple-400 mt-0.5">{{ riskMaxLeverage }}x</div>
            </div>
            <div>
              <label class="text-xs text-gray-500">日最大亏损 (%)</label>
              <NSlider v-model:value="riskMaxDailyLoss" :min="1" :max="50" :step="1" class="mt-1" />
              <div class="text-right text-xs text-purple-400 mt-0.5">{{ riskMaxDailyLoss }}%</div>
            </div>
            <div>
              <label class="text-xs text-gray-500">日最大交易次数</label>
              <NSlider v-model:value="riskMaxDailyTrades" :min="1" :max="100" :step="1" class="mt-1" />
              <div class="text-right text-xs text-purple-400 mt-0.5">{{ riskMaxDailyTrades }} 次</div>
            </div>
          </div>
        </template>

        <!-- Step 4: Basic Info -->
        <template v-if="wizardStep === 4 || editingStrategy">
          <div v-if="!editingStrategy" class="text-sm text-gray-300 mb-3">最后一步：填写策略名称</div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">策略名称</label>
            <NInput
              v-model:value="formName"
              placeholder="例如: RSI 超卖反弹策略"
              style="--n-color: #0f0f14; --n-border: 1px solid rgba(255,255,255,0.1); --n-text-color: white;"
            />
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs text-gray-500 mb-1.5">交易对</label>
              <NInput
                v-model:value="formSymbol"
                placeholder="BTCUSDT"
                style="--n-color: #0f0f14; --n-border: 1px solid rgba(255,255,255,0.1); --n-text-color: white;"
              />
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1.5">K线周期</label>
              <NSelect
                v-model:value="formInterval"
                :options="intervalOptions"
                style="--n-color: #0f0f14; --n-border: 1px solid rgba(255,255,255,0.1);"
              />
            </div>
          </div>
          <!-- Edit mode: show raw YAML -->
          <div v-if="editingStrategy">
            <label class="block text-xs text-gray-500 mb-1.5">策略配置 (YAML)</label>
            <NInput
              v-model:value="formYaml"
              type="textarea"
              :rows="12"
              style="--n-color: #0f0f14; --n-border: 1px solid rgba(255,255,255,0.1); --n-text-color: white; font-family: monospace; font-size: 13px;"
            />
          </div>
          <!-- Create mode: show preview -->
          <div v-else class="p-3 rounded-lg" style="background: rgba(255,255,255,0.02);">
            <div class="text-xs text-gray-500 mb-2">策略组合预览</div>
            <div class="flex items-center gap-2 text-xs">
              <span class="px-2 py-1 rounded" style="background: rgba(138,43,226,0.15); color: #a855f7;">{{ selectedAlpha === 'yaml_condition' ? '📊 技术指标' : '🤖 AI研判' }}</span>
              <span class="text-gray-600">→</span>
              <span class="px-2 py-1 rounded" style="background: rgba(34,197,94,0.1); color: #22c55e;">{{ selectedPortfolio === 'fixed_percent' ? '📐 固定比例' : '🎯 凯利公式' }}</span>
              <span class="text-gray-600">→</span>
              <span class="px-2 py-1 rounded" style="background: rgba(239,68,68,0.1); color: #ef4444;">🛡️ 风控 {{ riskMaxLeverage }}x</span>
              <span class="text-gray-600">→</span>
              <span class="px-2 py-1 rounded" style="background: rgba(59,130,246,0.1); color: #3b82f6;">⚡ 市价执行</span>
            </div>
          </div>
        </template>

        <!-- Navigation -->
        <div class="flex justify-between pt-2">
          <button
            v-if="wizardStep > 1 && !editingStrategy"
            @click="wizardStep--"
            class="px-4 py-2 rounded-lg text-sm text-gray-400 transition-colors"
            style="background: rgba(255,255,255,0.05);"
          >
            上一步
          </button>
          <div v-else></div>
          <div class="flex gap-3">
            <button
              @click="showCreateModal = false"
              class="px-4 py-2 rounded-lg text-sm text-gray-400 transition-colors"
              style="background: rgba(255,255,255,0.05);"
            >
              取消
            </button>
            <button
              v-if="wizardStep < 4 && !editingStrategy"
              @click="wizardStep++"
              class="px-4 py-2 rounded-lg text-sm text-white font-medium transition-all"
              style="background: linear-gradient(135deg, #8a2be2, #5a189a);"
            >
              下一步
            </button>
            <button
              v-if="wizardStep === 4 || editingStrategy"
              @click="handleSave"
              :disabled="formSaving"
              class="px-4 py-2 rounded-lg text-sm text-white font-medium transition-all flex items-center gap-2"
              style="background: linear-gradient(135deg, #8a2be2, #5a189a);"
            >
              <NSpin v-if="formSaving" size="small" />
              {{ editingStrategy ? '保存修改' : '创建策略' }}
            </button>
          </div>
        </div>
      </div>
    </NModal>

    <!-- Logs Modal -->
    <NModal
      v-model:show="showLogsModal"
      preset="card"
      :title="`执行日志 - ${viewingStrategyName}`"
      style="width: 800px; max-height: 80vh; background: #18181b; border: 1px solid rgba(255,255,255,0.06);"
      :bordered="false"
    >
      <div v-if="logsLoading" class="flex justify-center py-8">
        <NSpin size="medium" />
      </div>
      <div v-else-if="viewingLogs.length === 0" class="text-center py-8 text-gray-500">
        暂无日志记录
      </div>
      <div v-else class="space-y-2 max-h-[60vh] overflow-y-auto">
        <div
          v-for="log in viewingLogs"
          :key="log.id"
          class="rounded-lg p-3 text-sm"
          style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04);"
        >
          <div class="flex items-center justify-between mb-1">
            <div class="flex items-center gap-2">
              <span
                class="px-1.5 py-0.5 rounded text-xs font-mono"
                :style="{
                  background: log.action === 'execute' ? 'rgba(59,130,246,0.1)' : log.action === 'skip' ? 'rgba(234,179,8,0.1)' : 'rgba(107,114,128,0.1)',
                  color: log.action === 'execute' ? '#3b82f6' : log.action === 'skip' ? '#eab308' : '#6b7280',
                }"
              >
                {{ log.action.toUpperCase() }}
              </span>
              <span class="text-gray-300 font-mono">{{ log.signal_type }}</span>
              <span v-if="log.side" class="text-xs" :style="{ color: log.side === 'BUY' ? '#22c55e' : '#ef4444' }">
                {{ log.side }}
              </span>
            </div>
            <span class="text-xs text-gray-600">{{ formatDate(log.created_at) }}</span>
          </div>
          <div class="flex items-center gap-4 text-xs text-gray-500">
            <span v-if="log.ai_approve !== null">
              AI: {{ log.ai_approve ? '通过' : '拒绝' }}
              <span v-if="log.ai_confidence">({{ (log.ai_confidence * 100).toFixed(0) }}%)</span>
            </span>
            <span v-if="log.risk_passed !== null">
              风控: {{ log.risk_passed ? '通过' : '拦截' }}
            </span>
            <span v-if="log.pnl !== null" :style="{ color: pnlColor(log.pnl) }">
              PnL: {{ log.pnl >= 0 ? '+' : '' }}{{ log.pnl.toFixed(2) }}
            </span>
          </div>
          <div v-if="log.ai_reason" class="text-xs text-gray-600 mt-1 truncate">{{ log.ai_reason }}</div>
          <div v-if="log.risk_reason" class="text-xs text-red-400/60 mt-1">{{ log.risk_reason }}</div>
        </div>
      </div>
    </NModal>
  </MainLayout>
</template>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ==== New Styles ==== */
.create-btn {
  padding: 8px 16px;
  border-radius: 12px;
  color: white;
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
  background: linear-gradient(135deg, #8b5cf6, #6d28d9);
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
  transition: all 0.3s ease;
}

.create-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(139, 92, 246, 0.4);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.stat-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 16px;
  padding: 20px;
  transition: all 0.3s ease;
}

.stat-card:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.1);
  transform: translateY(-2px);
}

.stat-label {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  font-family: var(--font-family-mono);
  color: #f0f0f0;
}

.template-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  padding: 12px;
  text-align: left;
  transition: all 0.2s ease;
}

.template-card:hover {
  background: rgba(139, 92, 246, 0.1);
  border-color: rgba(139, 92, 246, 0.3);
  transform: translateY(-2px);
}

.strategy-card, .memory-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 16px;
  padding: 20px;
  transition: all 0.3s ease;
}

.strategy-card:hover, .memory-card:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(139, 92, 246, 0.3);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
  transform: translateX(4px);
}

/* ========== Mobile Responsive ========== */
@media (max-width: 768px) {
  .max-w-7xl {
    overflow-x: hidden;
    padding: 0 8px;
  }
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
  }
  .stat-card {
    padding: 12px;
  }
  .stat-value {
    font-size: 18px;
  }
  .strategy-card, .memory-card {
    padding: 12px;
  }
  .strategy-card:hover, .memory-card:hover {
    transform: none;
  }
  /* Header: stack title and button */
  .flex.items-center.justify-between {
    flex-wrap: wrap;
    gap: 8px;
  }
  .create-btn {
    padding: 6px 12px;
    font-size: 12px;
  }
  /* Strategy card: stack info + actions vertically */
  .strategy-card > .flex.items-center.justify-between {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
  .strategy-card > .flex > .flex.items-center.gap-2.flex-shrink-0 {
    align-self: flex-end;
  }
  /* Template cards: 2 columns on mobile */
  .grid.grid-cols-5 {
    grid-template-columns: repeat(2, 1fr) !important;
    gap: 8px;
  }
  .template-card {
    padding: 8px;
  }
  .template-card .text-sm {
    font-size: 12px;
  }
}

/* Pipeline Panel */
.pl-panel {
  background: linear-gradient(135deg, rgba(30,30,40,0.8) 0%, rgba(20,20,30,0.9) 100%);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 14px;
  padding: 18px 22px;
}
.pl-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.pl-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pl-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  animation: pulse-glow 2s ease-in-out infinite;
}
@keyframes pulse-glow {
  0%, 100% { opacity: 1; box-shadow: 0 0 4px currentColor; }
  50% { opacity: 0.6; box-shadow: 0 0 8px currentColor; }
}
.pl-title {
  font-size: 13px;
  font-weight: 700;
  color: #e5e7eb;
  letter-spacing: 0.3px;
}
.pl-badge {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 20px;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.pl-badge-ok {
  background: rgba(34,197,94,0.15);
  color: #4ade80;
  border: 1px solid rgba(34,197,94,0.25);
}
.pl-badge-danger {
  background: rgba(239,68,68,0.15);
  color: #f87171;
  border: 1px solid rgba(239,68,68,0.25);
}
.pl-flow {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
}
.pl-layer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.08);
  min-width: 120px;
  transition: all 0.25s ease;
}
.pl-layer:hover {
  transform: translateY(-2px);
  border-color: rgba(255,255,255,0.15);
}
.pl-layer--alpha { background: linear-gradient(135deg, rgba(168,85,247,0.12) 0%, rgba(139,92,246,0.06) 100%); }
.pl-layer--portfolio { background: linear-gradient(135deg, rgba(59,130,246,0.12) 0%, rgba(37,99,235,0.06) 100%); }
.pl-layer--risk { background: linear-gradient(135deg, rgba(245,158,11,0.12) 0%, rgba(217,119,6,0.06) 100%); }
.pl-layer--execution { background: linear-gradient(135deg, rgba(34,197,94,0.12) 0%, rgba(22,163,74,0.06) 100%); }

.pl-layer-icon {
  display: flex;
  align-items: center;
  justify-content: center;
}
.pl-layer-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid transparent;
}
.pl-layer-dot.active {
  background: #22c55e;
  border-color: rgba(34,197,94,0.3);
  box-shadow: 0 0 6px rgba(34,197,94,0.4);
}
.pl-layer-dot.idle {
  background: #4b5563;
  border-color: rgba(75,85,99,0.3);
}
.pl-layer-dot.error {
  background: #ef4444;
  border-color: rgba(239,68,68,0.3);
  box-shadow: 0 0 6px rgba(239,68,68,0.4);
}
.pl-layer-body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
}
.pl-layer-name {
  font-size: 12px;
  font-weight: 700;
  color: #e5e7eb;
}
.pl-layer-tag {
  font-size: 10px;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.pl-layer-count {
  font-size: 16px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
  color: #a1a1aa;
  min-width: 20px;
  text-align: right;
}
.pl-arrow {
  color: #4b5563;
  padding: 0 6px;
  display: flex;
  align-items: center;
}

@media (max-width: 768px) {
  .pl-flow {
    flex-wrap: wrap;
    gap: 6px;
  }
  .pl-layer {
    min-width: 0;
    flex: 1;
    padding: 8px 10px;
  }
  .pl-arrow {
    display: none;
  }
}

/* Decision Timeline */
.tl-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.tl-item {
  display: flex;
  gap: 14px;
  padding: 14px 0;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.tl-item:last-child { border-bottom: none; }
.tl-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-top: 5px;
  flex-shrink: 0;
  box-shadow: 0 0 6px currentColor;
}
.tl-content { flex: 1; min-width: 0; }
.tl-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.tl-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 4px;
  border: 1px solid;
}
.tl-symbol {
  font-size: 12px;
  font-weight: 600;
  color: #e5e7eb;
  font-family: 'JetBrains Mono', monospace;
}
.tl-strategy {
  font-size: 11px;
  color: #a78bfa;
  background: rgba(139,92,246,0.1);
  padding: 1px 6px;
  border-radius: 4px;
}
.tl-time {
  font-size: 11px;
  color: #4b5563;
  margin-left: auto;
}
.tl-summary {
  font-size: 13px;
  color: #d1d5db;
  line-height: 1.5;
}
.tl-thinking {
  margin-top: 8px;
}
.tl-thinking summary {
  font-size: 11px;
  color: #6b7280;
  cursor: pointer;
  user-select: none;
}
.tl-thinking summary:hover { color: #a78bfa; }
.tl-pre {
  font-size: 12px;
  color: #9ca3af;
  white-space: pre-wrap;
  word-break: break-all;
  background: rgba(0,0,0,0.2);
  padding: 10px;
  border-radius: 8px;
  margin-top: 6px;
  max-height: 300px;
  overflow-y: auto;
}

/* Trend Analysis */
.trend-card {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 16px;
  transition: border-color 0.2s;
}
.trend-card:hover { border-color: rgba(138,43,226,0.3); }
.trend-result { margin-top: 4px; }
.trend-regime {
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 8px;
}
.trend-metrics {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.trend-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.trend-metric-label {
  font-size: 10px;
  color: #6b7280;
  text-transform: uppercase;
}
.trend-metric-value {
  font-size: 13px;
  font-weight: 600;
  color: #e5e7eb;
  font-family: 'JetBrains Mono', monospace;
}
</style>
