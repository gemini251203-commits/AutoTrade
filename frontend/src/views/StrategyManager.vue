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
import { NIcon, NSpin, NModal, NInput, NSelect } from 'naive-ui'
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

// ==================== State ====================

const strategies = ref<StrategyResponse[]>([])
const templates = ref<StrategyTemplate[]>([])
const memories = ref<TradeMemoryResponse[]>([])
const loading = ref(false)
const error = ref('')

// Modal state
const showCreateModal = ref(false)
const showLogsModal = ref(false)
const showMemoryModal = ref(false)
const editingStrategy = ref<StrategyResponse | null>(null)
const viewingLogs = ref<StrategyLogResponse[]>([])
const viewingStrategyName = ref('')
const logsLoading = ref(false)

// Form state
const formName = ref('')
const formSymbol = ref('')
const formInterval = ref('1h')
const formYaml = ref('')
const formSaving = ref(false)

// Tab state
type TabKey = 'strategies' | 'memories'
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
  formName.value = template?.name || ''
  formSymbol.value = ''
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
  showCreateModal.value = true
}

async function handleSave() {
  if (!formName.value || !formSymbol.value || !formYaml.value) {
    error.value = '请填写所有必填项'
    return
  }
  formSaving.value = true
  try {
    const data = {
      name: formName.value,
      symbol: formSymbol.value.toUpperCase(),
      interval: formInterval.value,
      config_yaml: formYaml.value,
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

onMounted(() => {
  fetchAll()
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
    </div>

    <!-- Create/Edit Modal -->
    <NModal
      v-model:show="showCreateModal"
      preset="card"
      :title="editingStrategy ? '编辑策略' : '新建策略'"
      style="width: 640px; background: #18181b; border: 1px solid rgba(255,255,255,0.06);"
      :bordered="false"
    >
      <div class="space-y-4">
        <div>
          <label class="block text-xs text-gray-500 mb-1.5">策略名称</label>
          <NInput
            v-model:value="formName"
            placeholder="例如: RSI 反转策略"
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
        <div>
          <label class="block text-xs text-gray-500 mb-1.5">策略配置 (YAML)</label>
          <NInput
            v-model:value="formYaml"
            type="textarea"
            :rows="12"
            placeholder="name: my_strategy&#10;conditions:&#10;  operator: AND&#10;  items:&#10;    - indicator: rsi&#10;      comparator: less_than&#10;      value: 30"
            style="--n-color: #0f0f14; --n-border: 1px solid rgba(255,255,255,0.1); --n-text-color: white; font-family: monospace; font-size: 13px;"
          />
        </div>
        <div class="flex justify-end gap-3 pt-2">
          <button
            @click="showCreateModal = false"
            class="px-4 py-2 rounded-lg text-sm text-gray-400 transition-colors"
            style="background: rgba(255,255,255,0.05);"
          >
            取消
          </button>
          <button
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
</style>
