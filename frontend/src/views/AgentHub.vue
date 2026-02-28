<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import MainLayout from '@/layouts/MainLayout.vue'
import {
  NButton, NModal, NInput, NSelect, NSlider, NTag, NSpin,
  NEmpty, NIcon, NTooltip, NScrollbar,
} from 'naive-ui'
import {
  AddOutline, TrashOutline, PlayOutline, StopOutline,
  FlashOutline, SendOutline, CreateOutline,
} from '@vicons/ionicons5'
import {
  listHubAgents, createHubAgent, updateHubAgent, deleteHubAgent,
  controlHubAgent, getHubStatus, boardDeliberate, streamChatWithAgent,
  type HubAgent, type HubStatus, type BoardResult,
  type HubAgentCreateRequest, type HubAgentUpdateRequest,
} from '@/api/hub'

// ==================== State ====================

const agents = ref<HubAgent[]>([])
const hubStatus = ref<HubStatus | null>(null)
const loading = ref(false)

// 全局作战指示
const globalCommand = ref('')
const globalCommandLoading = ref(false)

// War Room Console
const warRoomMessages = ref<WRMessage[]>([])
const warRoomRef = ref<HTMLElement | null>(null)

// 编辑弹窗
const showEditModal = ref(false)
const editingAgent = ref<HubAgent | null>(null)
const editForm = ref<HubAgentCreateRequest & { id?: number }>({
  name: '', role: 'trader', avatar: 'BOT', provider: 'deepseek',
  model: 'deepseek-chat', api_base_url: null, api_key: null,
  system_prompt: '', temperature: 0.7,
})

// 轮询
let pollTimer: ReturnType<typeof setInterval> | null = null

interface WRMessage {
  id: number
  type: 'system' | 'ai_text' | 'tool_call' | 'tool_result' | 'error' | 'opinion' | 'consensus'
  avatar?: string
  name?: string
  content: string
  meta?: any
  time: string
}

let msgIdCounter = 0
function wrMsg(type: WRMessage['type'], content: string, opts: Partial<WRMessage> = {}): WRMessage {
  return {
    id: ++msgIdCounter,
    type,
    content,
    time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    ...opts,
  }
}

// Options
const roleOptions = [
  { label: 'Trader (交易员)', value: 'trader' },
  { label: 'Analyst (分析师)', value: 'analyst' },
  { label: 'Risk Advisor (风控顾问)', value: 'risk_advisor' },
]
// Avatar: use short code, frontend renders as initial letter circle
const avatarOptions = [
  { label: 'BOT', value: 'BOT' }, { label: 'FOX', value: 'FOX' },
  { label: 'WOLF', value: 'WOLF' }, { label: 'EAGLE', value: 'EAGLE' },
  { label: 'DRAGON', value: 'DRAGON' }, { label: 'BRAIN', value: 'BRAIN' },
  { label: 'BOLT', value: 'BOLT' }, { label: 'ORB', value: 'ORB' },
  { label: 'TARGET', value: 'TARGET' }, { label: 'PIRATE', value: 'PIRATE' },
]
const providerOptions = [
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'OpenAI', value: 'openai' },
  { label: 'Ollama', value: 'ollama' },
]

// Computed
const activeCount = computed(() => hubStatus.value?.active_count ?? 0)
const mode = computed(() => hubStatus.value?.mode ?? 'idle')

const modeLabel = computed(() => {
  const map: Record<string, string> = {
    idle: 'STANDBY', dictator: 'DICTATOR', board: 'BOARD',
  }
  return map[mode.value] || mode.value
})
const modeColor = computed(() => {
  const map: Record<string, string> = {
    idle: '#666', dictator: '#a855f7', board: '#3b82f6',
  }
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
  try {
    const [agentRes, statusRes] = await Promise.all([
      listHubAgents(), getHubStatus(),
    ])
    agents.value = (agentRes as any).data?.agents || (agentRes as any).agents || []
    hubStatus.value = (statusRes as any).data || statusRes as any
  } catch (e) {
    console.error('Failed to load hub data:', e)
  }
}

onMounted(async () => {
  loading.value = true
  await loadData()
  loading.value = false
  pollTimer = setInterval(loadData, 10000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

// Auto-scroll war room
function scrollWarRoom() {
  nextTick(() => {
    if (warRoomRef.value) {
      warRoomRef.value.scrollTop = warRoomRef.value.scrollHeight
    }
  })
}

// ==================== 全局作战指示 ====================

async function sendGlobalCommand() {
  const cmd = globalCommand.value.trim()
  if (!cmd || globalCommandLoading.value || activeCount.value === 0) return

  globalCommand.value = ''
  globalCommandLoading.value = true

  if (mode.value === 'dictator' && activeAgentForDictator.value) {
    // 独裁者: SSE 对话
    warRoomMessages.value.push(wrMsg('system', `[CMD] Dispatched: "${cmd}"`))
    scrollWarRoom()

    try {
      for await (const event of streamChatWithAgent(activeAgentForDictator.value.id, cmd)) {
        if (event.type === 'text' || event.type === 'done') {
          if (event.content) {
            warRoomMessages.value.push(wrMsg('ai_text', event.content, {
              avatar: activeAgentForDictator.value!.avatar,
              name: activeAgentForDictator.value!.name,
            }))
          }
        } else if (event.type === 'tool_call') {
          warRoomMessages.value.push(wrMsg('tool_call', `调用 ${event.tool}(${JSON.stringify(event.args || {}).slice(0, 80)})`, {
            avatar: 'TOOL',
            name: event.tool || 'Tool',
          }))
        } else if (event.type === 'tool_result') {
          const preview = (event.result || '').slice(0, 150)
          warRoomMessages.value.push(wrMsg('tool_result', `${event.tool} → ${preview}`, {
            avatar: 'OK',
            name: event.tool || 'Result',
          }))
        } else if (event.type === 'error') {
          warRoomMessages.value.push(wrMsg('error', event.content || '未知错误'))
        }
        scrollWarRoom()
      }
    } catch (e: any) {
      warRoomMessages.value.push(wrMsg('error', `连接失败: ${e.message}`))
    }

  } else if (mode.value === 'board') {
    // 董事会: 辩论
    warRoomMessages.value.push(wrMsg('system', `[BOARD] Topic: "${cmd}"`))
    warRoomMessages.value.push(wrMsg('system', `${activeCount.value} agents analyzing independently...`))
    scrollWarRoom()

    try {
      const res = await boardDeliberate(cmd, 'BTCUSDT')
      const result: BoardResult = (res as any).data || res as any

      // 每位 AI 的观点 → 群聊气泡
      for (const op of result.opinions) {
        const decisionLabel = op.decision === 'open_long' ? 'LONG' : op.decision === 'open_short' ? 'SHORT' : 'HOLD'
        warRoomMessages.value.push(wrMsg('opinion', op.reasoning, {
          avatar: op.avatar,
          name: op.agent_name,
          meta: { decision: decisionLabel, confidence: op.confidence },
        }))
        scrollWarRoom()
      }

      // 共识卡片
      warRoomMessages.value.push(wrMsg('consensus', '', { meta: result.consensus }))
      scrollWarRoom()
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
  editForm.value = {
    name: '', role: 'trader', avatar: 'BOT', provider: 'deepseek',
    model: 'deepseek-chat', api_base_url: null, api_key: null,
    system_prompt: '', temperature: 0.7,
  }
  showEditModal.value = true
}

function openEdit(agent: HubAgent) {
  editingAgent.value = agent
  editForm.value = {
    id: agent.id,
    name: agent.name, role: agent.role, avatar: agent.avatar,
    provider: agent.provider, model: agent.model,
    api_base_url: agent.api_base_url, api_key: null,
    system_prompt: agent.system_prompt, temperature: agent.temperature,
  }
  showEditModal.value = true
}

async function handleSave() {
  if (!editForm.value.name) return
  try {
    if (editingAgent.value) {
      const data: HubAgentUpdateRequest = {}
      const fields: (keyof HubAgentUpdateRequest)[] = ['name', 'role', 'avatar', 'provider', 'model', 'api_base_url', 'api_key', 'system_prompt', 'temperature']
      for (const f of fields) {
        const v = (editForm.value as any)[f]
        if (v !== null && v !== undefined && v !== '') (data as any)[f] = v
      }
      await updateHubAgent(editingAgent.value.id, data)
    } else {
      await createHubAgent(editForm.value)
    }
    showEditModal.value = false
    await loadData()
  } catch (e) {
    console.error('Save agent failed:', e)
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
      warRoomMessages.value.push(wrMsg('system', `[STARTED] ${agent?.name || `Agent #${id}`} activated`))
      scrollWarRoom()
    } else if (action === 'stop') {
      warRoomMessages.value.push(wrMsg('system', `[STOPPED] Agent #${id} deactivated`))
      scrollWarRoom()
    } else if (action === 'run_once') {
      const agent = agents.value.find(a => a.id === id)
      if (!agent) return
      warRoomMessages.value.push(wrMsg('system', `[TRIGGER] ${agent.name} 单次执行...`))
      scrollWarRoom()
      // 走 SSE 流式路径，实时显示思考过程
      try {
        const cyclePrompt = '定时巡逻: 查价格+指标，判断是否交易。言简意赅，只说关键数据和结论。'
        for await (const event of streamChatWithAgent(agent.id, cyclePrompt)) {
          if (event.type === 'text' || event.type === 'done') {
            if (event.content) {
              warRoomMessages.value.push(wrMsg('ai_text', event.content, {
                avatar: agent.avatar, name: agent.name,
              }))
            }
          } else if (event.type === 'tool_call') {
            warRoomMessages.value.push(wrMsg('tool_call', `调用 ${event.tool}(${JSON.stringify(event.args || {}).slice(0, 80)})`, {
              avatar: 'TOOL', name: event.tool || 'Tool',
            }))
          } else if (event.type === 'tool_result') {
            const preview = (event.result || '').slice(0, 150)
            warRoomMessages.value.push(wrMsg('tool_result', `${event.tool} → ${preview}`, {
              avatar: 'OK', name: event.tool || 'Result',
            }))
          } else if (event.type === 'error') {
            warRoomMessages.value.push(wrMsg('error', event.content || '未知错误'))
          }
          scrollWarRoom()
        }
        warRoomMessages.value.push(wrMsg('system', `[DONE] ${agent.name} 单次执行完成`))
        scrollWarRoom()
      } catch (e: any) {
        warRoomMessages.value.push(wrMsg('error', `执行失败: ${e.message}`))
      }
      await loadData()
    }
  } catch (e) {
    console.error('Control agent failed:', e)
  }
}

// Status helpers
function statusDot(status: string) {
  const map: Record<string, string> = {
    idle: '#666', active: '#22c55e', paused: '#eab308', error: '#ef4444',
  }
  return map[status] || '#666'
}
function statusLabel(status: string) {
  const map: Record<string, string> = {
    idle: '待命', active: '运行中', paused: '暂停', error: '错误',
  }
  return map[status] || status
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
          <div
            v-for="agent in agents"
            :key="agent.id"
            class="p-3 rounded-lg border transition-all duration-200 cursor-default"
            :style="{
              background: agent.is_active ? 'rgba(138,43,226,0.06)' : 'rgba(255,255,255,0.015)',
              borderColor: agent.is_active ? 'rgba(138,43,226,0.25)' : 'rgba(255,255,255,0.04)',
            }"
          >
            <!-- Agent Header -->
            <div class="flex items-center gap-2.5 mb-2">
              <span class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white" style="background: linear-gradient(135deg, #a855f7, #6366f1);">{{ agent.avatar?.charAt(0) || agent.name?.charAt(0) || 'A' }}</span>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span class="font-semibold text-white text-sm truncate">{{ agent.name }}</span>
                  <span class="flex items-center gap-1">
                    <span class="w-1.5 h-1.5 rounded-full" :style="{ background: statusDot(agent.status) }"></span>
                    <span class="text-[10px]" :style="{ color: statusDot(agent.status) }">{{ statusLabel(agent.status) }}</span>
                  </span>
                </div>
                <div class="text-[10px] text-gray-600 truncate">{{ agent.role }} · {{ agent.provider }}/{{ agent.model }}</div>
              </div>
            </div>

            <!-- Stats row -->
            <div class="flex items-center gap-3 mb-2 text-[10px] text-gray-500">
              <span>运行 <b class="text-gray-300">{{ agent.total_runs }}</b></span>
              <span>交易 <b class="text-purple-400">{{ agent.total_trades }}</b></span>
              <span>T° <b class="text-gray-300">{{ agent.temperature }}</b></span>
              <span v-if="agent.last_run_at" class="ml-auto text-gray-600 truncate" style="max-width: 100px;">{{ agent.last_run_at.slice(11, 19) }}</span>
            </div>

            <!-- Error -->
            <div v-if="agent.last_error" class="text-[10px] text-red-400 mb-2 p-1.5 rounded bg-red-500/10 truncate">
              [ERR] {{ agent.last_error }}
            </div>

            <!-- Actions -->
            <div class="flex gap-1.5">
              <NTooltip :delay="300" placement="bottom">
                <template #trigger>
                  <NButton v-if="!agent.is_active" size="tiny" type="success" quaternary @click="handleControl(agent.id, 'start')">
                    <template #icon><NIcon size="14"><PlayOutline /></NIcon></template>
                  </NButton>
                  <NButton v-else size="tiny" type="warning" quaternary @click="handleControl(agent.id, 'stop')">
                    <template #icon><NIcon size="14"><StopOutline /></NIcon></template>
                  </NButton>
                </template>
                {{ agent.is_active ? '停止' : '启动' }}
              </NTooltip>
              <NTooltip :delay="300" placement="bottom">
                <template #trigger>
                  <NButton size="tiny" quaternary @click="handleControl(agent.id, 'run_once')">
                    <template #icon><NIcon size="14"><FlashOutline /></NIcon></template>
                  </NButton>
                </template>
                单次执行
              </NTooltip>
              <NTooltip :delay="300" placement="bottom">
                <template #trigger>
                  <NButton size="tiny" quaternary @click="openEdit(agent)">
                    <template #icon><NIcon size="14"><CreateOutline /></NIcon></template>
                  </NButton>
                </template>
                编辑
              </NTooltip>
              <NTooltip :delay="300" placement="bottom">
                <template #trigger>
                  <NButton size="tiny" type="error" quaternary class="ml-auto" @click="handleDelete(agent.id)">
                    <template #icon><NIcon size="14"><TrashOutline /></NIcon></template>
                  </NButton>
                </template>
                删除
              </NTooltip>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== RIGHT: 作战指挥室 War Room (60%) ===== -->
      <div class="flex-1 flex flex-col min-h-0 rounded-xl border border-white/5 overflow-hidden" style="background: rgba(0,0,0,0.4);">
        <!-- War Room Header -->
        <div class="flex items-center gap-2 px-4 py-2.5 border-b border-white/5" style="background: rgba(0,0,0,0.3);">
          <span class="text-green-400 text-xs font-mono animate-pulse">●</span>
          <span class="text-xs font-semibold text-gray-300 tracking-wider font-mono">WAR ROOM CONSOLE</span>
          <span class="text-[10px] text-gray-600 ml-auto font-mono">{{ warRoomMessages.length }} events</span>
        </div>

        <!-- War Room Content -->
        <div ref="warRoomRef" class="flex-1 overflow-auto p-3 space-y-2 custom-scrollbar">
          <!-- Empty state -->
          <div v-if="warRoomMessages.length === 0" class="h-full flex items-center justify-center">
            <div class="text-center text-gray-600">
              <div class="text-3xl mb-3 font-mono text-gray-700">[~]</div>
              <div class="text-sm">War Room</div>
              <div class="text-xs text-gray-700 mt-1">Send a command above to see real-time AI actions</div>
            </div>
          </div>

          <!-- Messages -->
          <div
            v-for="msg in warRoomMessages"
            :key="msg.id"
            class="rounded-lg text-sm"
            :class="{
              'px-3 py-1.5 text-xs': msg.type === 'system',
              'p-3': msg.type !== 'system' && msg.type !== 'consensus',
            }"
          >
            <!-- System message -->
            <div v-if="msg.type === 'system'" class="text-gray-500 font-mono text-[11px] flex items-center gap-2">
              <span class="text-gray-700">{{ msg.time }}</span>
              <span>{{ msg.content }}</span>
            </div>

            <!-- AI Text -->
            <div v-else-if="msg.type === 'ai_text'" class="bg-white/[0.03] rounded-lg p-3">
              <div class="flex items-center gap-2 mb-1.5">
                <span class="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white" style="background: linear-gradient(135deg, #a855f7, #6366f1);">{{ msg.avatar?.charAt(0) || 'A' }}</span>
                <span class="text-xs font-semibold text-purple-300">{{ msg.name }}</span>
                <span class="text-[10px] text-gray-700 ml-auto font-mono">{{ msg.time }}</span>
              </div>
              <div class="text-gray-200 text-[13px] leading-relaxed whitespace-pre-wrap">{{ msg.content }}</div>
            </div>

            <!-- Tool Call -->
            <div v-else-if="msg.type === 'tool_call'" class="flex items-center gap-2 px-3 py-1.5 rounded bg-blue-500/5 border border-blue-500/10">
              <span class="text-xs font-mono text-blue-400">[TOOL]</span>
              <span class="text-[11px] font-mono text-blue-300 truncate">{{ msg.content }}</span>
              <span class="text-[10px] text-gray-700 ml-auto font-mono">{{ msg.time }}</span>
            </div>

            <!-- Tool Result -->
            <div v-else-if="msg.type === 'tool_result'" class="flex items-center gap-2 px-3 py-1.5 rounded bg-green-500/5 border border-green-500/10">
              <span class="text-xs font-mono text-green-400">[OK]</span>
              <span class="text-[11px] font-mono text-green-300 truncate">{{ msg.content }}</span>
              <span class="text-[10px] text-gray-700 ml-auto font-mono">{{ msg.time }}</span>
            </div>

            <!-- Board Opinion (群聊气泡) -->
            <div v-else-if="msg.type === 'opinion'" class="bg-white/[0.03] rounded-lg p-3">
              <div class="flex items-center gap-2 mb-1.5">
                <span class="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white" style="background: linear-gradient(135deg, #a855f7, #6366f1);">{{ msg.avatar?.charAt(0) || 'A' }}</span>
                <span class="text-xs font-bold text-white">{{ msg.name }}</span>
                <NTag
                  :type="msg.meta?.decision?.includes('做多') ? 'success' : msg.meta?.decision?.includes('做空') ? 'error' : 'default'"
                  size="tiny" round
                >
                  {{ msg.meta?.decision }}
                </NTag>
                <span class="text-[10px] text-gray-500 ml-auto">信心 {{ ((msg.meta?.confidence || 0) * 100).toFixed(0) }}%</span>
              </div>
              <div class="text-gray-300 text-xs leading-relaxed">{{ msg.content }}</div>
            </div>

            <!-- Consensus Card -->
            <div v-else-if="msg.type === 'consensus'" class="mx-auto max-w-md">
              <div class="p-4 rounded-xl border-2 border-purple-500/30 bg-gradient-to-br from-purple-500/10 to-blue-500/5">
                <div class="text-center mb-2">
                  <span class="text-xs font-bold text-purple-400 tracking-wider">CONSENSUS</span>
                </div>
                <div class="flex items-center justify-center gap-4 mb-2">
                  <NTag
                    :type="msg.meta?.decision === 'open_long' ? 'success' : msg.meta?.decision === 'open_short' ? 'error' : 'default'"
                    size="large" round
                  >
                    {{ msg.meta?.decision === 'open_long' ? 'LONG' : msg.meta?.decision === 'open_short' ? 'SHORT' : 'HOLD' }}
                  </NTag>
                </div>
                <div class="text-center text-xs text-gray-400 space-y-0.5">
                  <div>{{ msg.meta?.vote_count }}</div>
                  <div>平均信心: {{ ((msg.meta?.confidence || 0) * 100).toFixed(0) }}%</div>
                  <div v-if="msg.meta?.executed" class="text-green-400 font-semibold mt-1">
                    [EXECUTED] Order #{{ msg.meta?.order_id }}
                  </div>
                  <div v-else class="text-gray-600 mt-1">未触发交易</div>
                </div>
              </div>
            </div>

            <!-- Error -->
            <div v-else-if="msg.type === 'error'" class="px-3 py-1.5 rounded bg-red-500/10 border border-red-500/10">
              <span class="text-xs text-red-400">[ERROR] {{ msg.content }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 编辑 / 创建弹窗 ========== -->
    <NModal
      v-model:show="showEditModal"
      preset="card"
      :title="editingAgent ? `Edit ${editingAgent.name}` : 'Create Agent'"
      style="max-width: 600px; max-height: 90vh;"
      :mask-closable="false"
    >
      <div class="space-y-4 overflow-auto" style="max-height: 70vh;">
        <!-- Row 1: Name + Avatar -->
        <div class="grid grid-cols-3 gap-3">
          <div class="col-span-2">
            <label class="text-[11px] text-gray-500 mb-1 block font-semibold">名称</label>
            <NInput v-model:value="editForm.name" placeholder="e.g. Alpha 猎手" />
          </div>
          <div>
            <label class="text-[11px] text-gray-500 mb-1 block font-semibold">头像</label>
            <NSelect v-model:value="editForm.avatar" :options="avatarOptions" />
          </div>
        </div>

        <!-- Row 2: Role + Provider + Model -->
        <div class="grid grid-cols-3 gap-3">
          <div>
            <label class="text-[11px] text-gray-500 mb-1 block font-semibold">角色</label>
            <NSelect v-model:value="editForm.role" :options="roleOptions" />
          </div>
          <div>
            <label class="text-[11px] text-gray-500 mb-1 block font-semibold">AI 供应商</label>
            <NSelect v-model:value="editForm.provider" :options="providerOptions" />
          </div>
          <div>
            <label class="text-[11px] text-gray-500 mb-1 block font-semibold">模型</label>
            <NInput v-model:value="editForm.model" placeholder="deepseek-chat" />
          </div>
        </div>

        <!-- Row 3: API Key + Temperature -->
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="text-[11px] text-gray-500 mb-1 block font-semibold">API Key <span class="text-gray-700">(可选，覆盖全局)</span></label>
            <NInput v-model:value="editForm.api_key" type="password" show-password-on="click" placeholder="留空则使用全局配置" />
          </div>
          <div>
            <label class="text-[11px] text-gray-500 mb-1 block font-semibold">温度 ({{ editForm.temperature }})</label>
            <NSlider v-model:value="editForm.temperature" :min="0" :max="2" :step="0.1" class="mt-2" />
          </div>
        </div>

        <!-- Row 4: System Prompt (巨大输入框) -->
        <div>
          <label class="text-[11px] text-gray-500 mb-1.5 block font-semibold">
            System Prompt (KPI)
            <span class="text-gray-700 font-normal ml-2">— 在这里写入角色定位、交易风格、绩效目标</span>
          </label>
          <div class="rounded-lg border border-white/10 overflow-hidden" style="background: rgba(0,0,0,0.3);">
            <NInput
              v-model:value="editForm.system_prompt"
              type="textarea"
              :autosize="{ minRows: 10, maxRows: 20 }"
              placeholder="示例:

你是 Alpha 猎手，一个激进但精准的短线交易员。

【你的 KPI】
- 3天内赚 200 USDT
- 单笔止损不超过 2%
- 胜率目标 60%+
- 不追高，只在回调确认后进场
- 优先交易 BTC 和 ETH

【你的交易风格】
- 基于技术指标（RSI、MACD、布林带）做决策
- 只在趋势明确时入场
- 到达止盈目标后主动平仓"
              style="font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 12px; line-height: 1.6;"
            />
          </div>
        </div>
      </div>

      <template #action>
        <div class="flex justify-end gap-3">
          <NButton @click="showEditModal = false">取消</NButton>
          <NButton type="primary" @click="handleSave" :disabled="!editForm.name">
            {{ editingAgent ? '保存修改' : '创建' }}
          </NButton>
        </div>
      </template>
    </NModal>
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
