<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import MainLayout from '@/layouts/MainLayout.vue'
import {
  NButton, NSelect, NInput, NIcon, NSpin, NEmpty, useMessage,
} from 'naive-ui'
import {
  AddOutline, SendOutline, DocumentTextOutline, CalendarOutline,
} from '@vicons/ionicons5'
import {
  listHubAgents, createHubAgent, updateHubAgent, deleteHubAgent,
  controlHubAgent, getHubStatus, boardDeliberate, streamChatWithAgent,
  getHubLogs, saveHubLog, triggerConsolidation, setSecretary, getSecretary, clearHubLogs,
  getWakeConditions,
  type HubAgent, type HubStatus, type BoardResult,
  type HubAgentUpdateRequest,
  type WakeConditionsResponse,
} from '@/api/hub'

// 子组件
import AgentCard from './hub/AgentCard.vue'
import WarRoom from './hub/WarRoom.vue'
import EditAgentModal from './hub/EditAgentModal.vue'
import MinutesCalendar from './hub/MinutesCalendar.vue'

import type { WRMessage } from './hub/WarRoom.vue'

// ==================== State ====================

const agents = ref<HubAgent[]>([])
const hubStatus = ref<HubStatus | null>(null)
const loading = ref(false)
const message = useMessage()

// 唤醒条件状态
const wakeConditionsMap = ref<Record<number, WakeConditionsResponse>>({})

// 全局作战指示
const globalCommand = ref('')
const globalCommandLoading = ref(false)
const consolidating = ref(false)
const secretaryAgentId = ref<number | null>(null)

// 连接健康状态
const connectionStatus = ref<'connected' | 'reconnecting' | 'error'>('reconnecting')
let pollFailCount = 0

// War Room Console
const warRoomMessages = ref<WRMessage[]>([])

// 编辑弹窗
const showEditModal = ref(false)
const editingAgent = ref<HubAgent | null>(null)
const editModalRef = ref<InstanceType<typeof EditAgentModal> | null>(null)

// 纪要日历弹窗
const showMinutesModal = ref(false)
const minutesCalendarRef = ref<InstanceType<typeof MinutesCalendar> | null>(null)

// 日志搜索
const logSearchKeyword = ref('')
const logSearchLoading = ref(false)
const logPage = ref(1)
const logPageSize = 15
const logHasMore = ref(false)

// 轮询
let pollTimer: ReturnType<typeof setInterval> | null = null
let _unmounted = false
let _loadingData = false

// ==================== WRMessage Helpers ====================

let msgIdCounter = 0
function wrMsg(type: WRMessage['type'], content: string, opts: Partial<WRMessage> = {}): WRMessage {
  const now = new Date()
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const dd = String(now.getDate()).padStart(2, '0')
  const time = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Shanghai' })
  return {
    id: ++msgIdCounter,
    type,
    content,
    time: `${mm}-${dd} ${time}`,
    ...opts,
  }
}

/** 后端 UTC 时间 → 北京时间 HH:mm:ss */
function _utc2beijing(utcStr?: string): string {
  if (!utcStr) return ''
  try {
    const d = new Date(utcStr.endsWith('Z') ? utcStr : utcStr + 'Z')
    const mm = String(d.toLocaleString('en', { month: '2-digit', timeZone: 'Asia/Shanghai' }))
    const dd = String(d.toLocaleString('en', { day: '2-digit', timeZone: 'Asia/Shanghai' }))
    const time = d.toLocaleTimeString('zh-CN', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      timeZone: 'Asia/Shanghai',
    })
    return `${mm}-${dd} ${time}`
  } catch {
    return utcStr.slice(5, 19) || ''
  }
}

// ========== 日志格式化 ==========
const TOOL_LABELS: Record<string, string> = {
  get_balance: '查询余额', get_positions: '查询持仓', get_indicators: '获取行情',
  get_price: '查询价格', get_klines: '获取K线', get_funding_rate: '查询资金费率',
  get_market_sentiment: '市场情绪', place_order: '下单', close_position: '平仓',
  get_trade_journal: '查阅日志', manage_grid: '管理网格', analyze_trend_now: '趋势分析',
  search_historical_minutes: '检索纪要', get_market_overview: '市场概览',
  set_leverage: '设置杠杆', set_stop_loss: '设置止损', set_take_profit: '设置止盈',
}

function extractToolName(raw: string): string {
  const match = raw.replace(/^\[TOOL\]\s*/, '').match(/^(\w+)/)
  return match?.[1] || 'unknown'
}
function toolLabel(name: string): string {
  return TOOL_LABELS[name] || name
}

/** 将连续的 tool_call/tool_result 折叠为 tool_trace 摘要行 */
function collapseToolLogs(msgs: WRMessage[]): WRMessage[] {
  const result: WRMessage[] = []
  let toolChain: string[] = []
  let chainTime = ''
  let chainName = ''

  function flushChain() {
    if (toolChain.length === 0) return
    const count = toolChain.length
    result.push(wrMsg('tool_trace' as any, `${count}`, { time: chainTime, name: chainName }))
    toolChain = []
  }

  for (const m of msgs) {
    if (m.type === 'tool_call') {
      const name = extractToolName(m.content)
      toolChain.push(toolLabel(name))
      chainTime = m.time || ''
      chainName = m.name || ''
    } else if (m.type === 'tool_result') {
      // 吞掉
    } else {
      flushChain()
      result.push(m)
    }
  }
  flushChain()
  return result
}

// ==================== Computed ====================

const activeCount = computed(() => hubStatus.value?.active_count ?? 0)
const mode = computed(() => hubStatus.value?.mode ?? 'idle')

const secretaryOptions = computed(() => {
  return agents.value.map(a => ({ label: `${a.name} (${a.model})`, value: a.id }))
})

const modeLabel = computed(() => {
  const map: Record<string, string> = { idle: 'STANDBY', dictator: 'DICTATOR', board: 'BOARD' }
  return map[mode.value] || mode.value
})
const modeColor = computed(() => {
  const map: Record<string, string> = { idle: '#666', dictator: '#a855f7', board: '#3b82f6' }
  return map[mode.value] || '#666'
})

const activeAgentForDictator = computed(() => {
  if (mode.value !== 'dictator') return null
  return agents.value.find(a => a.is_active) || null
})

const commandPlaceholder = computed(() => {
  if (activeCount.value === 0) return '请先激活至少一个智能体...'
  if (mode.value === 'dictator') return '输入作战指令，直接发给 AI 执行... (例: "分析 BTC 趋势，如果有机会就做多")'
  return '输入辩论议题，触发多 AI 董事会... (例: "目前是熊市，不要抢多单，合作帮我赚钱")'
})

// ==================== Data Loading ====================

async function loadData() {
  if (_loadingData || _unmounted) return
  _loadingData = true
  try {
    const [agentRes, statusRes, secRes] = await Promise.all([
      listHubAgents(), getHubStatus(), getSecretary().catch(() => null),
    ])
    agents.value = (agentRes as any)?.agents || []
    hubStatus.value = statusRes as any
    if (secRes) {
      secretaryAgentId.value = (secRes as any)?.secretary_agent_id ?? null
    }
    // 并行加载活跃 agent 的唤醒条件
    const activeAgents = agents.value.filter(a => a.is_active)
    if (activeAgents.length > 0) {
      const wakeResults = await Promise.allSettled(
        activeAgents.map(a => getWakeConditions(a.id))
      )
      const newMap: Record<number, WakeConditionsResponse> = {}
      wakeResults.forEach((result, idx) => {
        if (result.status === 'fulfilled') {
          const data = result.value as any
          if (data?.has_conditions) {
            newMap[activeAgents[idx]!.id] = data
          }
        }
      })
      wakeConditionsMap.value = newMap
    } else {
      wakeConditionsMap.value = {}
    }
    connectionStatus.value = 'connected'
    pollFailCount = 0
  } catch (e) {
    pollFailCount++
    connectionStatus.value = pollFailCount >= 3 ? 'error' : 'reconnecting'
    console.error(`Failed to load hub data (attempt ${pollFailCount}):`, e)
  } finally {
    _loadingData = false
  }
}

// ==================== 日志搜索 + 分页 ====================

async function loadWarRoomHistory(keyword?: string, page?: number, autoScroll = true) {
  try {
    logSearchLoading.value = true
    const p = page ?? logPage.value
    const params: any = { limit: logPageSize, offset: (p - 1) * logPageSize }
    if (keyword) params.keyword = keyword
    const res = await getHubLogs(params)
    const data = res as any
    const logs = data?.logs || []
    logHasMore.value = data?.has_more ?? (logs.length >= logPageSize)
    logPage.value = p

    const newFirstTime = logs[0]?.created_at || ''
    const oldFirstTime = (warRoomMessages.value[0] as any)?._rawTime || ''
    const hasNewContent = newFirstTime !== oldFirstTime

    warRoomMessages.value = collapseToolLogs(logs.map((log: any) => {
      const msg = wrMsg(
        log.log_type as WRMessage['type'],
        log.content,
        { name: log.agent_name, time: _utc2beijing(log.created_at) }
      )
      ;(msg as any)._rawTime = log.created_at
      return msg
    }))
  } catch (e) {
    console.error('Failed to load war room history:', e)
  } finally {
    logSearchLoading.value = false
  }
}

function logPrevPage() {
  if (logPage.value > 1) loadWarRoomHistory(logSearchKeyword.value || undefined, logPage.value - 1)
}
function logNextPage() {
  if (logHasMore.value) loadWarRoomHistory(logSearchKeyword.value || undefined, logPage.value + 1)
}

/** 推送一条消息到 War Room 并异步保存到后端 */
function pushAndSave(
  type: WRMessage['type'],
  content: string,
  opts: Partial<WRMessage> & { agentId?: number | null; agentName?: string } = {},
) {
  const msg = wrMsg(type, content, opts)
  warRoomMessages.value.unshift(msg)
  if (warRoomMessages.value.length > 100) warRoomMessages.value.length = 100
  saveHubLog({
    agent_id: opts.agentId ?? null,
    agent_name: opts.agentName || opts.name || 'System',
    log_type: type,
    content,
  }).catch(() => {})
  return msg
}

async function searchLogs() {
  await loadWarRoomHistory(logSearchKeyword.value.trim() || undefined)
}

// ==================== Lifecycle ====================

onMounted(() => {
  _unmounted = false
  loading.value = true
  Promise.all([loadData(), loadWarRoomHistory()]).finally(() => {
    loading.value = false
  })
  pollTimer = setInterval(() => {
    if (!_unmounted && !_loadingData) {
      loadData()
      if (!logSearchKeyword.value && logPage.value === 1 && !consolidating.value) {
        loadWarRoomHistory()
      }
    }
  }, 10000)
})

onUnmounted(() => {
  _unmounted = true
  if (pollTimer) clearInterval(pollTimer)
})

// ==================== 全局作战指示 ====================

async function sendGlobalCommand() {
  const cmd = globalCommand.value.trim()
  if (!cmd || globalCommandLoading.value || activeCount.value === 0) return

  globalCommand.value = ''
  globalCommandLoading.value = true

  if (mode.value === 'dictator' && activeAgentForDictator.value) {
    pushAndSave('system', `[CMD] ${cmd}`)
    try {
      for await (const event of streamChatWithAgent(activeAgentForDictator.value.id, cmd)) {
        if (event.type === 'text' || event.type === 'done') {
          if (event.content) {
            pushAndSave('ai_text', event.content, {
              avatar: activeAgentForDictator.value!.avatar,
              name: activeAgentForDictator.value!.name,
              agentId: activeAgentForDictator.value!.id,
              agentName: activeAgentForDictator.value!.name,
            })
          }
        } else if (event.type === 'error') {
          warRoomMessages.value.push(wrMsg('error', event.content || '未知错误'))
        }
      }
    } catch (e: any) {
      warRoomMessages.value.push(wrMsg('error', `连接失败: ${e.message}`))
    }
  } else if (mode.value === 'board') {
    warRoomMessages.value.push(wrMsg('system', `[BOARD] Topic: "${cmd}"`))
    warRoomMessages.value.push(wrMsg('system', `${activeCount.value} agents analyzing independently...`))
    try {
      const res = await boardDeliberate(cmd, 'BTCUSDT')
      const result: BoardResult = res as any
      for (const op of result.opinions) {
        const decisionLabel = op.decision === 'open_long' ? 'LONG' : op.decision === 'open_short' ? 'SHORT' : 'HOLD'
        warRoomMessages.value.push(wrMsg('opinion', op.reasoning, {
          avatar: op.avatar, name: op.agent_name,
          meta: { decision: decisionLabel, confidence: op.confidence },
        }))
      }
      warRoomMessages.value.push(wrMsg('consensus', '', { meta: result.consensus }))
    } catch (e: any) {
      warRoomMessages.value.push(wrMsg('error', `辩论失败: ${e.message}`))
    }
  }

  globalCommandLoading.value = false
  await loadData()
}

// ==================== CRUD ====================

function openCreate() {
  editingAgent.value = null
  showEditModal.value = true
  nextTick(() => editModalRef.value?.openCreate())
}

function openEdit(agent: HubAgent) {
  editingAgent.value = agent
  showEditModal.value = true
  nextTick(() => editModalRef.value?.openEdit(agent))
}

async function handleSave(payload: { form: any; isEdit: boolean; promptChanged: boolean }) {
  try {
    if (payload.isEdit && editingAgent.value) {
      const data: HubAgentUpdateRequest = {}
      const fields: (keyof HubAgentUpdateRequest)[] = ['name', 'role', 'avatar', 'provider', 'model', 'api_base_url', 'api_key', 'system_prompt', 'temperature', 'polling_interval']
      for (const f of fields) {
        const v = payload.form[f]
        if (v !== null && v !== undefined && v !== '') (data as any)[f] = v
      }
      data.allowed_tools = payload.form.allowed_tools

      if (editingAgent.value.active_template_id && payload.promptChanged && payload.form.system_prompt) {
        data.active_template_id = null
        message.info('已自动解绑提示词模板，您的手动编辑将直接生效')
      }

      await updateHubAgent(editingAgent.value.id, data)
      message.success('保存成功')
    } else {
      await createHubAgent(payload.form)
      message.success('创建成功')
    }
    showEditModal.value = false
    await loadData()
  } catch (e: any) {
    console.error('Save agent failed:', e)
    message.error(`保存失败: ${e?.response?.data?.detail || e?.message || '未知错误'}`)
  }
}

async function handleDelete(id: number) {
  try {
    await deleteHubAgent(id)
    await loadData()
  } catch (e) {
    console.error('Delete agent failed:', e)
  }
}

async function handleControl(id: number, action: string) {
  try {
    await controlHubAgent(id, action)
    await loadData()
    if (action === 'start') {
      const agent = agents.value.find(a => a.id === id)
      pushAndSave('system', `[STARTED] ${agent?.name || `Agent #${id}`} activated`)
    } else if (action === 'stop') {
      pushAndSave('system', `[STOPPED] Agent #${id} deactivated`)
    } else if (action === 'run_once') {
      const agent = agents.value.find(a => a.id === id)
      if (!agent) return
      pushAndSave('system', `[TRIGGER] ${agent.name} 单次执行...`, { agentId: agent.id, agentName: agent.name })
      try {
        const cyclePrompt = '轮到你值班了。你需要关注以下交易对: BTCUSDT、ETHUSDT、SOLUSDT、BNBUSDT。\n1. 先查看当前持仓情况（所有币种），了解你的仓位状况。\n2. 逐一检查各币种的行情和技术指标，寻找交易机会。\n3. 如果发现好的机会，自己判断要不要开仓或调整仓位。\n4. 如果没有机会，保持观望并简要汇报各币种情况。\n注意: 调用工具时请明确指定 symbol 参数，不要只看默认的 BTC。'
        for await (const event of streamChatWithAgent(agent.id, cyclePrompt)) {
          if (event.type === 'text' || event.type === 'done') {
            if (event.content) {
              pushAndSave('ai_text', event.content, {
                avatar: agent.avatar, name: agent.name,
                agentId: agent.id, agentName: agent.name,
              })
            }
          } else if (event.type === 'ping') {
            // 心跳包，忽略
          } else if (event.type === 'error') {
            warRoomMessages.value.push(wrMsg('error', event.content || '未知错误'))
          }
        }
        pushAndSave('system', `[DONE] ${agent.name} 单次执行完成`, { agentId: agent.id, agentName: agent.name })
      } catch (e: any) {
        warRoomMessages.value.push(wrMsg('error', `执行失败: ${e.message}`))
      }
      await loadData()
    }
  } catch (e) {
    console.error('Control agent failed:', e)
  }
}

// ==================== 纪要生成 + 书记员 + 清空 ====================

let _consolidationPromise: Promise<any> | null = null

async function handleConsolidate() {
  if (_consolidationPromise) {
    message.warning('纪要正在生成中，请稍候...')
    return
  }
  consolidating.value = true
  warRoomMessages.value.unshift(wrMsg('system', '[System] 正在生成今日《董事会纪要》，可能需要 30-60 秒...', { name: 'System' }))

  const token = (await import('@/utils/request')).getAuthToken()
  _consolidationPromise = fetch('/api/hub/memory/consolidate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  }).then(async (resp) => {
    if (!resp.ok) {
      const body = await resp.text().catch(() => '')
      throw new Error(`生成失败 (${resp.status}): ${body}`)
    }
    return resp.json()
  })

  try {
    const data = await _consolidationPromise
    const text = `[今日董事会纪要] (重要性: ${data.importance}/10)\n\n${data.summary}\n\n[核心教训]: ${data.key_lessons}`
    try { await saveHubLog({ agent_name: '书记员', log_type: 'ai_text', content: text }) } catch {}
    await loadWarRoomHistory()
    message.success('董事会纪要生成成功！')
  } catch (e: any) {
    warRoomMessages.value.unshift(wrMsg('error', `纪要生成失败: ${e?.message || e}`, { name: 'System' }))
    message.error(`纪要生成失败: ${e?.message || '未知错误'}`)
  } finally {
    consolidating.value = false
    _consolidationPromise = null
  }
}

async function handleClearLogs() {
  try {
    await clearHubLogs()
    warRoomMessages.value = []
  } catch (e: any) {
    console.error('clear logs failed', e)
  }
}

async function handleSecretaryChange(val: number | null) {
  secretaryAgentId.value = val
  try {
    await setSecretary(val)
    const name = agents.value.find(a => a.id === val)?.name || '系统默认'
    warRoomMessages.value.push(wrMsg('system', `首席书记员已切换为: ${name}`, { name: 'System' }))
  } catch (e: any) {
    console.error('set secretary failed', e)
  }
}

function openMinutesCalendar() {
  showMinutesModal.value = true
  nextTick(() => minutesCalendarRef.value?.open())
}
</script>

<template>
  <MainLayout>
  <div class="max-w-[1600px] mx-auto space-y-4 h-full flex flex-col">

    <!-- ========== Header ========== -->
    <div class="flex items-center justify-between flex-shrink-0">
      <div class="flex items-center gap-3">
        <h1 class="text-xl font-bold text-white">Agent Hub</h1>
        <span
          class="text-xs px-3 py-1 rounded-full font-medium tracking-wide"
          :style="{ background: modeColor + '15', color: modeColor, border: '1px solid ' + modeColor + '30' }"
        >
          {{ modeLabel }}
        </span>
      </div>
      <div class="flex items-center gap-4 text-xs text-gray-500">
        <NSelect
          :value="secretaryAgentId"
          :options="secretaryOptions"
          placeholder="指定书记员"
          clearable
          size="tiny"
          style="width: 160px;"
          @update:value="handleSecretaryChange"
        />
        <NButton
          size="tiny"
          :loading="consolidating"
          @click="handleConsolidate"
          class="!text-[11px]"
          style="background: linear-gradient(135deg, #a855f7 0%, #6366f1 100%); border: none; color: white;"
        >
          <template #icon><NIcon :component="DocumentTextOutline" /></template>
          立刻生成今日复盘
        </NButton>
        <NButton
          size="tiny"
          @click="openMinutesCalendar"
          class="!text-[11px]"
          style="background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%); border: none; color: white;"
        >
          <template #icon><NIcon :component="CalendarOutline" /></template>
          历史纪要
        </NButton>
        <span>智能体 <b class="text-white">{{ agents.length }}</b></span>
        <span>运行中 <b class="text-green-400">{{ activeCount }}</b></span>
        <span>累计交易 <b class="text-purple-400">{{ agents.reduce((s, a) => s + a.total_trades, 0) }}</b></span>
      </div>
    </div>

    <!-- ========== ZONE 1: 全局作战指示 ========== -->
    <div class="flex-shrink-0 p-4 rounded-xl border border-white/5 bg-white/[0.02] backdrop-blur">
      <div class="flex items-center gap-2 mb-2">
        <span class="text-xs font-semibold" :style="{ color: modeColor }">
          {{ mode === 'dictator' ? 'CMD > Execute' : mode === 'board' ? 'TOPIC > Deliberate' : 'Global Command' }}
        </span>
        <span v-if="mode === 'dictator' && activeAgentForDictator" class="text-xs text-gray-500">
          > {{ activeAgentForDictator.name }}
        </span>
      </div>
      <div class="flex gap-2">
        <NInput
          v-model:value="globalCommand"
          :placeholder="commandPlaceholder"
          :disabled="activeCount === 0 || globalCommandLoading"
          @keyup.enter="sendGlobalCommand"
          class="flex-1"
          size="large"
        />
        <NButton
          type="primary"
          size="large"
          :loading="globalCommandLoading"
          :disabled="activeCount === 0 || !globalCommand.trim()"
          @click="sendGlobalCommand"
          style="min-width: 80px;"
        >
          <template #icon><NIcon><SendOutline /></NIcon></template>
          {{ mode === 'board' ? '辩论' : '发送' }}
        </NButton>
      </div>
    </div>

    <!-- ========== ZONE 2 + ZONE 3: 双栏主体 ========== -->
    <div class="flex-1 flex gap-4 min-h-0">

      <!-- ===== LEFT: 员工列表 (40%) ===== -->
      <div class="w-[38%] flex flex-col min-h-0">
        <div class="flex items-center justify-between mb-3 flex-shrink-0">
          <span class="text-sm font-semibold text-gray-400">Agents</span>
          <NButton size="small" type="primary" quaternary @click="openCreate">
            <template #icon><NIcon><AddOutline /></NIcon></template>
            新建
          </NButton>
        </div>

        <div v-if="loading" class="flex-1 flex items-center justify-center">
          <NSpin size="large" />
        </div>

        <div v-else-if="agents.length === 0" class="flex-1 flex items-center justify-center">
          <NEmpty description="还没有创建任何智能体">
            <template #extra>
              <NButton type="primary" size="small" @click="openCreate">创建第一个智能体</NButton>
            </template>
          </NEmpty>
        </div>

        <div v-else class="flex-1 overflow-auto space-y-2 pr-1 custom-scrollbar">
          <AgentCard
            v-for="agent in agents"
            :key="agent.id"
            :agent="agent"
            :wake-conditions="wakeConditionsMap[agent.id]"
            @control="handleControl"
            @edit="openEdit"
            @delete="handleDelete"
          />
        </div>
      </div>

      <!-- ===== RIGHT: 作战指挥室 War Room (60%) ===== -->
      <WarRoom
        :messages="warRoomMessages"
        :connection-status="connectionStatus"
        :log-search-keyword="logSearchKeyword"
        :log-search-loading="logSearchLoading"
        :log-page="logPage"
        :log-has-more="logHasMore"
        @update:log-search-keyword="logSearchKeyword = $event"
        @search="searchLogs"
        @clear-search="loadWarRoomHistory()"
        @clear-logs="handleClearLogs"
        @prev-page="logPrevPage"
        @next-page="logNextPage"
      />
    </div>

    <!-- ========== 编辑 / 创建弹窗 ========== -->
    <EditAgentModal
      ref="editModalRef"
      v-model:show="showEditModal"
      :editing-agent="editingAgent"
      @save="handleSave"
    />

    <!-- ========== 历史纪要日历 ========== -->
    <MinutesCalendar
      ref="minutesCalendarRef"
      v-model:show="showMinutesModal"
    />
  </div>
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
