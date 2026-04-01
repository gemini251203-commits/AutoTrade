<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import MainLayout from '@/layouts/MainLayout.vue'
import {
  NButton, NModal, NInput, NTag, NSpin, NEmpty, NIcon,
  NTooltip, NSelect, NSwitch, NTabs, NTabPane, useMessage,
  NPopconfirm,
} from 'naive-ui'
import {
  AddOutline, TrashOutline, CreateOutline, CopyOutline,
  FlashOutline, ChevronForwardOutline, TrophyOutline,
  CheckmarkCircleOutline, CloseCircleOutline,
  DocumentTextOutline, RocketOutline, ShieldCheckmarkOutline,
  PulseOutline, LinkOutline, UnlinkOutline,
} from '@vicons/ionicons5'
import {
  listTemplates, createTemplate, updateTemplate, deleteTemplate,
  activateTemplate, deactivateTemplate, getTemplatePerformance,
  duplicateTemplate, recommendTemplate,
  type PromptTemplate, type PromptTemplateCreateRequest,
  type PromptTemplateUpdateRequest, type TemplatePerformance,
} from '@/api/prompt'
import { listHubAgents, type HubAgent } from '@/api/hub'

const message = useMessage()

// ==================== State ====================
const templates = ref<PromptTemplate[]>([])
const agents = ref<HubAgent[]>([])
const loading = ref(false)
const selectedId = ref<number | null>(null)

// 编辑弹窗
const showEditor = ref(false)
const editorMode = ref<'create' | 'edit'>('create')
const editorForm = ref<PromptTemplateCreateRequest & { id?: number }>({
  name: '',
  description: '',
  strategy_prompt: '',
  risk_rules: '',
  behavior_directives: '',
  raw_prompt: '',
  is_structured: true,
  market_tags: null,
})
const saving = ref(false)

// 收益面板
const perfData = ref<TemplatePerformance | null>(null)
const perfLoading = ref(false)

// 推荐
const recommendation = ref<PromptTemplate | null>(null)
const recLoading = ref(false)

// 激活弹窗
const showActivateModal = ref(false)
const activateTemplateId = ref<number | null>(null)
const activateAgentId = ref<number | null>(null)
const activating = ref(false)

// ==================== Options ====================
const marketTagOptions = [
  { label: ' 趋势上涨', value: 'trending_up' },
  { label: ' 趋势下跌', value: 'trending_down' },
  { label: '️ 横盘震荡', value: 'sideways' },
  { label: ' 剧烈波动', value: 'high_volatility' },
  { label: ' 小资金 (<1000U)', value: 'small_fund' },
  { label: ' 中资金 (1000-10000U)', value: 'medium_fund' },
  { label: ' 大资金 (>10000U)', value: 'large_fund' },
]

const agentOptions = computed(() =>
  agents.value.map(a => ({
    label: `${a.name} (${a.model})`,
    value: a.id,
  }))
)

// ==================== Computed ====================
const selectedTemplate = computed(() =>
  templates.value.find(t => t.id === selectedId.value) || null
)

const userTemplates = computed(() =>
  templates.value.filter(t => !t.is_preset)
)
const presetTemplates = computed(() =>
  templates.value.filter(t => t.is_preset)
)

// 找到绑定了某个模板的 agent 列表
function boundAgents(templateId: number): HubAgent[] {
  return agents.value.filter(a => (a as any).active_template_id === templateId)
}

// ==================== Data Loading ====================
async function loadData() {
  loading.value = true
  try {
    const [tRes, aRes] = await Promise.all([
      listTemplates(true),
      listHubAgents(),
    ])
    templates.value = (tRes as any).data?.templates || (tRes as any).templates || []
    agents.value = (aRes as any).data?.agents || (aRes as any).agents || []
  } catch (e) {
    console.error('Load prompt data failed:', e)
  } finally {
    loading.value = false
  }
}

async function loadPerf(id: number) {
  perfLoading.value = true
  perfData.value = null
  try {
    const res = await getTemplatePerformance(id)
    perfData.value = (res as any).data || res as any
  } catch (e) {
    console.error('Load performance failed:', e)
  } finally {
    perfLoading.value = false
  }
}

async function loadRecommendation() {
  recLoading.value = true
  try {
    const res = await recommendTemplate()
    const data = (res as any).data || res as any
    recommendation.value = data?.recommendation || null
  } catch (e) {
    console.error('Load recommendation failed:', e)
  } finally {
    recLoading.value = false
  }
}

// Watch selected template -> load perf
watch(selectedId, (id) => {
  if (id) loadPerf(id)
  else perfData.value = null
})

onMounted(async () => {
  await loadData()
  loadRecommendation()
})

// ==================== CRUD ====================
function openCreate() {
  editorMode.value = 'create'
  editorForm.value = {
    name: '',
    description: '',
    strategy_prompt: '',
    risk_rules: '',
    behavior_directives: '',
    raw_prompt: '',
    is_structured: true,
    market_tags: null,
  }
  showEditor.value = true
}

function openEdit(t: PromptTemplate) {
  editorMode.value = 'edit'
  editorForm.value = {
    id: t.id,
    name: t.name,
    description: t.description || '',
    strategy_prompt: t.strategy_prompt,
    risk_rules: t.risk_rules,
    behavior_directives: t.behavior_directives,
    raw_prompt: t.raw_prompt,
    is_structured: t.is_structured,
    market_tags: t.market_tags ? [...t.market_tags] : null,
  }
  showEditor.value = true
}

async function handleSave() {
  if (!editorForm.value.name.trim()) {
    message.warning('请填写模板名称')
    return
  }
  saving.value = true
  try {
    if (editorMode.value === 'edit' && editorForm.value.id) {
      const { id, ...rest } = editorForm.value
      await updateTemplate(id, rest as PromptTemplateUpdateRequest)
      message.success('模板已更新')
    } else {
      await createTemplate(editorForm.value)
      message.success('模板已创建')
    }
    showEditor.value = false
    await loadData()
  } catch (e: any) {
    message.error(`保存失败: ${e?.message || e}`)
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await deleteTemplate(id)
    message.success('模板已删除')
    if (selectedId.value === id) selectedId.value = null
    await loadData()
  } catch (e: any) {
    message.error(`删除失败: ${e?.message || e}`)
  }
}

async function handleDuplicate(id: number) {
  try {
    await duplicateTemplate(id)
    message.success('模板已复制')
    await loadData()
  } catch (e: any) {
    message.error(`复制失败: ${e?.message || e}`)
  }
}

// ==================== Activate / Deactivate ====================
function openActivate(templateId: number) {
  activateTemplateId.value = templateId
  activateAgentId.value = null
  showActivateModal.value = true
}

async function handleActivate() {
  if (!activateTemplateId.value || !activateAgentId.value) return
  activating.value = true
  try {
    const res = await activateTemplate(activateTemplateId.value, activateAgentId.value)
    const data = (res as any).data || res as any
    message.success(data?.message || '已激活')
    showActivateModal.value = false
    await loadData()
  } catch (e: any) {
    message.error(`激活失败: ${e?.message || e}`)
  } finally {
    activating.value = false
  }
}

async function handleDeactivate(templateId: number, agentId: number) {
  try {
    await deactivateTemplate(templateId, agentId)
    message.success('已取消绑定')
    await loadData()
  } catch (e: any) {
    message.error(`取消绑定失败: ${e?.message || e}`)
  }
}

// ==================== Helpers ====================
function pnlColor(val: number) {
  return val > 0 ? '#00e676' : val < 0 ? '#ff1744' : '#999'
}
function pnlSign(val: number) {
  return val > 0 ? '+' : ''
}

const marketTagLabels: Record<string, string> = {
  trending_up: '趋势上涨',
  trending_down: '趋势下跌',
  sideways: '横盘震荡',
  high_volatility: '剧烈波动',
  small_fund: '小资金',
  medium_fund: '中资金',
  large_fund: '大资金',
}
function tagLabel(tag: string) {
  return marketTagLabels[tag] || tag
}
function tagIcon(tag: string) {
  const icons: Record<string, string> = {
    trending_up: '', trending_down: '', sideways: '️',
    high_volatility: '', small_fund: '', medium_fund: '', large_fund: '',
  }
  return icons[tag] || '️'
}

function formatTime(iso: string) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) + ' ' +
           d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso.slice(0, 16)
  }
}
</script>

<template>
  <MainLayout>
  <div class="max-w-[1600px] mx-auto space-y-4 h-full flex flex-col">

    <!-- ========== Header ========== -->
    <div class="flex items-center justify-between flex-shrink-0">
      <div class="flex items-center gap-3">
        <h1 class="text-xl font-bold text-white">提示词管理</h1>
        <span class="text-xs px-3 py-1 rounded-full font-medium text-purple-300 bg-purple-500/10 border border-purple-500/20">
          Prompt Templates
        </span>
      </div>
      <div class="flex items-center gap-3">
        <NButton
          size="small"
          :loading="recLoading"
          @click="loadRecommendation"
          class="!text-[11px]"
          style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); border: none; color: white;"
        >
          <template #icon><NIcon :component="TrophyOutline" /></template>
          市况推荐
        </NButton>
        <NButton size="small" type="primary" @click="openCreate">
          <template #icon><NIcon><AddOutline /></NIcon></template>
          新建模板
        </NButton>
      </div>
    </div>

    <!-- ========== 推荐卡片 ========== -->
    <div
      v-if="recommendation"
      class="flex-shrink-0 p-3 rounded-xl border border-amber-500/20 bg-amber-500/5 backdrop-blur flex items-center gap-4"
    >
      <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center text-white text-lg flex-shrink-0">
        <NIcon :component="TrophyOutline" size="22" />
      </div>
      <div class="flex-1 min-w-0">
        <div class="text-xs text-amber-400 font-medium mb-0.5">系统推荐最佳模板</div>
        <div class="text-sm text-white font-semibold truncate">
          {{ recommendation.name }}
          <span class="text-xs text-gray-400 ml-1">v{{ recommendation.version }}</span>
        </div>
      </div>
      <div class="flex items-center gap-4 text-xs flex-shrink-0">
        <div class="text-center">
          <div class="text-gray-500">胜率</div>
          <div class="font-mono font-bold text-amber-400">{{ recommendation.win_rate }}%</div>
        </div>
        <div class="text-center">
          <div class="text-gray-500">盈亏</div>
          <div class="font-mono font-bold" :style="{ color: pnlColor(recommendation.total_pnl) }">
            {{ pnlSign(recommendation.total_pnl) }}{{ recommendation.total_pnl.toFixed(2) }}
          </div>
        </div>
        <NButton size="tiny" type="warning" quaternary @click="openActivate(recommendation.id)">
          激活
        </NButton>
      </div>
    </div>

    <!-- ========== 主体：双栏布局 ========== -->
    <div class="flex-1 flex gap-4 min-h-0">

      <!-- ===== LEFT: 模板列表 (40%) ===== -->
      <div class="w-[38%] flex flex-col min-h-0">

        <!-- 预置模板 -->
        <div v-if="presetTemplates.length > 0" class="mb-3 flex-shrink-0">
          <div class="text-xs text-gray-500 font-semibold mb-2 flex items-center gap-1.5">
            <NIcon :component="RocketOutline" size="14" />
            预置模板库
          </div>
          <div class="space-y-1.5">
            <div
              v-for="t in presetTemplates" :key="t.id"
              @click="selectedId = t.id"
              class="group p-2.5 rounded-lg border transition-all cursor-pointer"
              :class="selectedId === t.id
                ? 'border-purple-500/40 bg-purple-500/10'
                : 'border-white/5 bg-white/[0.02] hover:border-white/10 hover:bg-white/[0.04]'"
            >
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2 min-w-0">
                  <div class="w-7 h-7 rounded-md bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                    P
                  </div>
                  <div class="min-w-0">
                    <div class="text-sm text-white font-medium truncate">{{ t.name }}</div>
                    <div class="text-[10px] text-gray-500 truncate">{{ t.description || '系统预置' }}</div>
                  </div>
                </div>
                <NButton size="tiny" quaternary @click.stop="handleDuplicate(t.id)" class="opacity-0 group-hover:opacity-100 transition-opacity">
                  <template #icon><NIcon :component="CopyOutline" size="14" /></template>
                </NButton>
              </div>
              <div v-if="t.market_tags?.length" class="flex flex-wrap gap-1 mt-1.5">
                <span
                  v-for="tag in t.market_tags" :key="tag"
                  class="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-gray-400"
                >
                  {{ tagIcon(tag) }} {{ tagLabel(tag) }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 分隔线 -->
        <div v-if="presetTemplates.length > 0 && userTemplates.length > 0" class="h-px bg-white/5 my-2 flex-shrink-0" />

        <!-- 用户模板 -->
        <div class="text-xs text-gray-500 font-semibold mb-2 flex items-center gap-1.5 flex-shrink-0">
          <NIcon :component="DocumentTextOutline" size="14" />
          我的模板
          <span class="text-gray-600 ml-1">({{ userTemplates.length }})</span>
        </div>

        <div v-if="loading" class="flex-1 flex items-center justify-center">
          <NSpin size="large" />
        </div>

        <div v-else-if="userTemplates.length === 0" class="flex-1 flex items-center justify-center">
          <NEmpty description="还没有自定义模板">
            <template #extra>
              <NButton size="small" @click="openCreate">创建第一个模板</NButton>
            </template>
          </NEmpty>
        </div>

        <div v-else class="flex-1 overflow-y-auto space-y-1.5 pr-1 custom-scrollbar">
          <div
            v-for="t in userTemplates" :key="t.id"
            @click="selectedId = t.id"
            class="group p-3 rounded-lg border transition-all cursor-pointer"
            :class="selectedId === t.id
              ? 'border-purple-500/40 bg-purple-500/10'
              : 'border-white/5 bg-white/[0.02] hover:border-white/10 hover:bg-white/[0.04]'"
          >
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2.5 min-w-0 flex-1">
                <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-blue-600 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                  {{ t.name.charAt(0) }}
                </div>
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-1.5">
                    <span class="text-sm text-white font-medium truncate">{{ t.name }}</span>
                    <span class="text-[10px] text-gray-500">v{{ t.version }}</span>
                  </div>
                  <div class="text-[10px] text-gray-500 truncate">
                    {{ t.description || (t.is_structured ? '结构化模板' : '自由文本模板') }}
                  </div>
                </div>
              </div>

              <!-- 收益标签 -->
              <div class="flex items-center gap-2 flex-shrink-0">
                <div v-if="t.total_trades > 0" class="text-right">
                  <div class="text-[10px] font-mono" :style="{ color: pnlColor(t.total_pnl) }">
                    {{ pnlSign(t.total_pnl) }}{{ t.total_pnl.toFixed(2) }}
                  </div>
                  <div class="text-[9px] text-gray-600">{{ t.total_trades  }}笔 | {{ t.win_rate }}%</div>
                </div>

                <!-- 绑定状态 -->
                <div v-if="boundAgents(t.id).length > 0">
                  <NTooltip>
                    <template #trigger>
                      <div class="w-5 h-5 rounded-full bg-green-500/20 flex items-center justify-center">
                        <NIcon :component="LinkOutline" size="12" class="text-green-400" />
                      </div>
                    </template>
                    已绑定: {{ boundAgents(t.id).map(a => a.name).join(', ') }}
                  </NTooltip>
                </div>
              </div>
            </div>

            <!-- 市况标签 -->
            <div v-if="t.market_tags?.length" class="flex flex-wrap gap-1 mt-2">
              <span
                v-for="tag in t.market_tags" :key="tag"
                class="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-gray-400"
              >
                {{ tagIcon(tag) }} {{ tagLabel(tag) }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== RIGHT: 详情面板 (60%) ===== -->
      <div class="flex-1 flex flex-col min-h-0">
        <div v-if="!selectedTemplate" class="flex-1 flex items-center justify-center">
          <div class="text-center text-gray-500">
            <NIcon :component="DocumentTextOutline" size="48" class="mb-3 opacity-30" />
            <div class="text-sm">选择一个模板查看详情</div>
            <div class="text-[10px] mt-1">或点击右上角新建模板</div>
          </div>
        </div>

        <div v-else class="flex-1 overflow-y-auto space-y-4 pr-1 custom-scrollbar">
          <!-- 模板头部 -->
          <div class="p-4 rounded-xl border border-white/5 bg-white/[0.02] backdrop-blur">
            <div class="flex items-start justify-between mb-3">
              <div>
                <div class="flex items-center gap-2">
                  <h2 class="text-lg font-bold text-white">{{ selectedTemplate.name }}</h2>
                  <span class="text-xs px-2 py-0.5 rounded bg-white/5 text-gray-400">v{{ selectedTemplate.version }}</span>
                  <NTag v-if="selectedTemplate.is_preset" size="tiny" :bordered="false" type="info">预置</NTag>
                  <NTag v-if="selectedTemplate.is_structured" size="tiny" :bordered="false" type="success">结构化</NTag>
                  <NTag v-else size="tiny" :bordered="false">自由文本</NTag>
                </div>
                <div class="text-xs text-gray-500 mt-1">
                  {{ selectedTemplate.description || '无描述' }}
                  <span class="ml-3">创建于 {{ formatTime(selectedTemplate.created_at) }}</span>
                </div>
              </div>
              <div class="flex items-center gap-1.5">
                <NTooltip>
                  <template #trigger>
                    <NButton size="tiny" quaternary @click="openActivate(selectedTemplate.id)">
                      <template #icon><NIcon :component="FlashOutline" size="16" /></template>
                    </NButton>
                  </template>
                  激活到 Agent
                </NTooltip>
                <NTooltip>
                  <template #trigger>
                    <NButton size="tiny" quaternary @click="handleDuplicate(selectedTemplate.id)">
                      <template #icon><NIcon :component="CopyOutline" size="16" /></template>
                    </NButton>
                  </template>
                  复制模板
                </NTooltip>
                <NTooltip v-if="!selectedTemplate.is_preset">
                  <template #trigger>
                    <NButton size="tiny" quaternary @click="openEdit(selectedTemplate)">
                      <template #icon><NIcon :component="CreateOutline" size="16" /></template>
                    </NButton>
                  </template>
                  编辑
                </NTooltip>
                <NPopconfirm
                  v-if="!selectedTemplate.is_preset"
                  @positive-click="handleDelete(selectedTemplate.id)"
                >
                  <template #trigger>
                    <NButton size="tiny" quaternary type="error">
                      <template #icon><NIcon :component="TrashOutline" size="16" /></template>
                    </NButton>
                  </template>
                  确认删除此模板？
                </NPopconfirm>
              </div>
            </div>

            <!-- 绑定的 Agent 列表 -->
            <div v-if="boundAgents(selectedTemplate.id).length > 0" class="flex items-center gap-2 mt-2 pt-2 border-t border-white/5">
              <span class="text-[10px] text-gray-500 flex-shrink-0">已绑定:</span>
              <div v-for="a in boundAgents(selectedTemplate.id)" :key="a.id" class="flex items-center gap-1">
                <NTag size="tiny" :bordered="false" closable @close="handleDeactivate(selectedTemplate.id, a.id)">
                  {{ a.name }}
                </NTag>
              </div>
            </div>

            <!-- 市况标签 -->
            <div v-if="selectedTemplate.market_tags?.length" class="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-white/5">
              <span
                v-for="tag in selectedTemplate.market_tags" :key="tag"
                class="text-xs px-2 py-0.5 rounded-md bg-white/5 text-gray-300"
              >
                {{ tagIcon(tag) }} {{ tagLabel(tag) }}
              </span>
            </div>
          </div>

          <!-- 收益面板 -->
          <div class="p-4 rounded-xl border border-white/5 bg-white/[0.02] backdrop-blur">
            <div class="text-xs text-gray-500 font-semibold mb-3 flex items-center gap-1.5">
              <NIcon :component="PulseOutline" size="14" />
              收益表现
            </div>
            <div v-if="perfLoading" class="flex justify-center py-4">
              <NSpin size="small" />
            </div>
            <div v-else-if="perfData" class="grid grid-cols-4 gap-4">
              <div class="text-center">
                <div class="text-[10px] text-gray-500 mb-1">总交易</div>
                <div class="text-lg font-bold font-mono text-white">{{ perfData.total_trades }}</div>
              </div>
              <div class="text-center">
                <div class="text-[10px] text-gray-500 mb-1">胜率</div>
                <div class="text-lg font-bold font-mono" :style="{ color: perfData.win_rate >= 50 ? '#00e676' : '#ff1744' }">
                  {{ perfData.win_rate }}%
                </div>
              </div>
              <div class="text-center">
                <div class="text-[10px] text-gray-500 mb-1">总盈亏</div>
                <div class="text-lg font-bold font-mono" :style="{ color: pnlColor(perfData.total_pnl) }">
                  {{ pnlSign(perfData.total_pnl) }}{{ perfData.total_pnl.toFixed(2) }}
                </div>
              </div>
              <div class="text-center">
                <div class="text-[10px] text-gray-500 mb-1">盈 / 亏</div>
                <div class="text-lg font-bold font-mono text-white">
                  <span class="text-green-400">{{ perfData.win_trades }}</span>
                  <span class="text-gray-600 mx-0.5">/</span>
                  <span class="text-red-400">{{ perfData.loss_trades }}</span>
                </div>
              </div>
            </div>
            <div v-else class="text-center py-4 text-xs text-gray-600">暂无交易数据</div>
          </div>

          <!-- 提示词内容 -->
          <div class="p-4 rounded-xl border border-white/5 bg-white/[0.02] backdrop-blur">
            <div class="text-xs text-gray-500 font-semibold mb-3 flex items-center gap-1.5">
              <NIcon :component="DocumentTextOutline" size="14" />
              提示词内容
            </div>

            <div v-if="selectedTemplate.is_structured" class="space-y-3">
              <!-- 策略 -->
              <div v-if="selectedTemplate.strategy_prompt">
                <div class="flex items-center gap-1.5 mb-1">
                  <div class="w-1.5 h-1.5 rounded-full bg-blue-400" />
                  <span class="text-[10px] text-blue-400 font-semibold uppercase tracking-wider">交易策略</span>
                </div>
                <pre class="text-xs text-gray-300 whitespace-pre-wrap bg-black/30 rounded-lg p-3 border border-white/5 font-sans leading-relaxed">{{ selectedTemplate.strategy_prompt }}</pre>
              </div>

              <!-- 风控 -->
              <div v-if="selectedTemplate.risk_rules">
                <div class="flex items-center gap-1.5 mb-1">
                  <div class="w-1.5 h-1.5 rounded-full bg-red-400" />
                  <span class="text-[10px] text-red-400 font-semibold uppercase tracking-wider">风控规则</span>
                </div>
                <pre class="text-xs text-gray-300 whitespace-pre-wrap bg-black/30 rounded-lg p-3 border border-white/5 font-sans leading-relaxed">{{ selectedTemplate.risk_rules }}</pre>
              </div>

              <!-- 行为指令 -->
              <div v-if="selectedTemplate.behavior_directives">
                <div class="flex items-center gap-1.5 mb-1">
                  <div class="w-1.5 h-1.5 rounded-full bg-green-400" />
                  <span class="text-[10px] text-green-400 font-semibold uppercase tracking-wider">行为指令</span>
                </div>
                <pre class="text-xs text-gray-300 whitespace-pre-wrap bg-black/30 rounded-lg p-3 border border-white/5 font-sans leading-relaxed">{{ selectedTemplate.behavior_directives }}</pre>
              </div>
            </div>

            <!-- 自由文本模式 -->
            <div v-else>
              <pre class="text-xs text-gray-300 whitespace-pre-wrap bg-black/30 rounded-lg p-3 border border-white/5 font-sans leading-relaxed">{{ selectedTemplate.raw_prompt || '(空)' }}</pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ========== 编辑弹窗 ========== -->
  <NModal
    v-model:show="showEditor"
    preset="card"
    :title="editorMode === 'create' ? '新建提示词模板' : '编辑模板'"
    style="width: 720px; max-height: 85vh;"
    :bordered="false"
    :mask-closable="!saving"
    class="prompt-modal"
    content-style="overflow-y: auto;"
  >
    <div class="space-y-4">
      <!-- 名称 -->
      <div>
        <label class="text-xs text-gray-400 mb-1 block">模板名称 *</label>
        <NInput v-model:value="editorForm.name" placeholder="如: 保守防守v2, 趋势追踪" />
      </div>

      <!-- 描述 -->
      <div>
        <label class="text-xs text-gray-400 mb-1 block">描述 (可选)</label>
        <NInput v-model:value="editorForm.description" placeholder="简要描述模板的用途和特点" />
      </div>

      <!-- 模式切换 -->
      <div class="flex items-center gap-3 p-2 rounded-lg bg-white/5">
        <span class="text-xs text-gray-400">编辑模式:</span>
        <NSwitch v-model:value="editorForm.is_structured" />
        <span class="text-xs" :class="editorForm.is_structured ? 'text-purple-400' : 'text-gray-400'">
          {{ editorForm.is_structured ? '结构化 (推荐)' : '自由文本' }}
        </span>
      </div>

      <!-- 结构化编辑器 -->
      <div v-if="editorForm.is_structured" class="space-y-4">
        <div>
          <label class="text-xs text-blue-400 mb-1 flex items-center gap-1">
            <div class="w-1.5 h-1.5 rounded-full bg-blue-400" />
            交易策略
          </label>
          <NInput
            v-model:value="editorForm.strategy_prompt"
            type="textarea"
            :rows="6"
            placeholder="【身份定义】&#10;你是...，你的交易风格是...&#10;&#10;【交易策略 - 核心规则】&#10;1. 趋势判断：...&#10;2. 入场条件：...&#10;3. 仓位管理：..."
          />
        </div>
        <div>
          <label class="text-xs text-red-400 mb-1 flex items-center gap-1">
            <div class="w-1.5 h-1.5 rounded-full bg-red-400" />
            风控规则
          </label>
          <NInput
            v-model:value="editorForm.risk_rules"
            type="textarea"
            :rows="4"
            placeholder="【风控规则 - 最高优先级】&#10;- 禁止同时持有超过3个仓位&#10;- 单笔仓位不超过账户余额的 20%&#10;- 当日亏损超过 5% 时停止交易"
          />
        </div>
        <div>
          <label class="text-xs text-green-400 mb-1 flex items-center gap-1">
            <div class="w-1.5 h-1.5 rounded-full bg-green-400" />
            行为指令 (可选)
          </label>
          <NInput
            v-model:value="editorForm.behavior_directives"
            type="textarea"
            :rows="3"
            placeholder="回复控制在 200 字以内&#10;观望时 100 字以内即可&#10;不要使用 Emoji"
          />
        </div>
      </div>

      <!-- 自由文本编辑器 -->
      <div v-else>
        <label class="text-xs text-gray-400 mb-1 block">自由文本提示词</label>
        <NInput
          v-model:value="editorForm.raw_prompt"
          type="textarea"
          :rows="12"
          placeholder="直接撰写完整的提示词内容..."
        />
      </div>

      <!-- 市况标签 -->
      <div>
        <label class="text-xs text-gray-400 mb-1 block">适用市况标签 (可选)</label>
        <NSelect
          v-model:value="editorForm.market_tags"
          :options="marketTagOptions"
          multiple
          clearable
          placeholder="选择适用的市况..."
        />
      </div>
    </div>

    <!-- 底部按钮 -->
    <template #footer>
      <div class="flex items-center justify-end gap-2">
        <NButton @click="showEditor = false" :disabled="saving">取消</NButton>
        <NButton type="primary" :loading="saving" @click="handleSave">
          {{ editorMode === 'create' ? '创建' : '保存' }}
        </NButton>
      </div>
    </template>
  </NModal>

  <!-- ========== 激活弹窗 ========== -->
  <NModal
    v-model:show="showActivateModal"
    preset="card"
    title="激活模板到 Agent"
    style="width: 480px;"
    :bordered="false"
    class="prompt-modal"
  >
    <div class="space-y-4">
      <div class="text-sm text-gray-300">
        选择要绑定的智能体，模板内容将作为 Agent 的交易策略指令。
      </div>
      <NSelect
        v-model:value="activateAgentId"
        :options="agentOptions"
        placeholder="选择 Agent..."
        size="large"
      />
    </div>
    <template #footer>
      <div class="flex items-center justify-end gap-2">
        <NButton @click="showActivateModal = false">取消</NButton>
        <NButton
          type="primary"
          :loading="activating"
          :disabled="!activateAgentId"
          @click="handleActivate"
        >
          <template #icon><NIcon :component="FlashOutline" /></template>
          激活
        </NButton>
      </div>
    </template>
  </NModal>

  </MainLayout>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 4px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 99px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.15);
}
</style>
