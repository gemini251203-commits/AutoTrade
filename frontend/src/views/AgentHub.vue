<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NButton, NCard, NModal, NInput, NSelect, NSlider,
  NTag, NSpin, NEmpty, NIcon, NTooltip, NInputNumber,
} from 'naive-ui'
import {
  AddOutline, TrashOutline, PlayOutline, StopOutline,
  FlashOutline, ChatboxEllipsesOutline, PeopleOutline,
} from '@vicons/ionicons5'
import {
  listHubAgents, createHubAgent, updateHubAgent, deleteHubAgent,
  controlHubAgent, getHubStatus, boardDeliberate, streamChatWithAgent,
  type HubAgent, type HubStatus, type BoardResult,
  type HubAgentCreateRequest,
} from '@/api/hub'

// ==================== State ====================

const agents = ref<HubAgent[]>([])
const hubStatus = ref<HubStatus | null>(null)
const loading = ref(false)

// Create modal
const showCreateModal = ref(false)
const createForm = ref<HubAgentCreateRequest>({
  name: '',
  role: 'trader',
  avatar: '🤖',
  provider: 'deepseek',
  model: 'deepseek-chat',
  api_base_url: null,
  api_key: null,
  system_prompt: '',
  temperature: 0.7,
})

// Chat modal (Dictator mode)
const showChatModal = ref(false)
const chatAgentId = ref<number | null>(null)
const chatMessages = ref<{ role: string; content: string; tool?: string }[]>([])
const chatInput = ref('')
const chatLoading = ref(false)

// Board modal
const showBoardModal = ref(false)
const boardTopic = ref('')
const boardSymbol = ref('BTCUSDT')
const boardResult = ref<BoardResult | null>(null)
const boardLoading = ref(false)

// Options
const roleOptions = [
  { label: '🏹 交易员 (Trader)', value: 'trader' },
  { label: '📊 分析师 (Analyst)', value: 'analyst' },
  { label: '🛡️ 风控顾问 (Risk Advisor)', value: 'risk_advisor' },
]

const avatarOptions = [
  { label: '🤖', value: '🤖' }, { label: '🦊', value: '🦊' },
  { label: '🐺', value: '🐺' }, { label: '🦅', value: '🦅' },
  { label: '🐉', value: '🐉' }, { label: '🧠', value: '🧠' },
  { label: '⚡', value: '⚡' }, { label: '🔮', value: '🔮' },
]

const providerOptions = [
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'OpenAI', value: 'openai' },
  { label: 'Ollama', value: 'ollama' },
]

// Computed
const modeLabel = computed(() => {
  if (!hubStatus.value) return '—'
  const map: Record<string, string> = {
    idle: '💤 待命',
    dictator: '👑 独裁者模式',
    board: '🏛️ 董事会模式',
  }
  return map[hubStatus.value.mode] || hubStatus.value.mode
})

const modeColor = computed(() => {
  if (!hubStatus.value) return '#666'
  const map: Record<string, string> = {
    idle: '#666',
    dictator: '#a855f7',
    board: '#3b82f6',
  }
  return map[hubStatus.value.mode] || '#666'
})

// ==================== Data Loading ====================

async function loadData() {
  loading.value = true
  try {
    const [agentRes, statusRes] = await Promise.all([
      listHubAgents(),
      getHubStatus(),
    ])
    agents.value = (agentRes as any).data?.agents || (agentRes as any).agents || []
    hubStatus.value = (statusRes as any).data || statusRes as any
  } catch (e) {
    console.error('Failed to load hub data:', e)
  } finally {
    loading.value = false
  }
}

onMounted(loadData)

// ==================== CRUD ====================

async function handleCreate() {
  if (!createForm.value.name) return
  try {
    await createHubAgent(createForm.value)
    showCreateModal.value = false
    createForm.value = {
      name: '', role: 'trader', avatar: '🤖', provider: 'deepseek',
      model: 'deepseek-chat', api_base_url: null, api_key: null,
      system_prompt: '', temperature: 0.7,
    }
    await loadData()
  } catch (e) {
    console.error('Create agent failed:', e)
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
  } catch (e) {
    console.error('Control agent failed:', e)
  }
}

// ==================== Chat (Dictator) ====================

function openChat(agent: HubAgent) {
  chatAgentId.value = agent.id
  chatMessages.value = []
  chatInput.value = ''
  showChatModal.value = true
}

async function sendChat() {
  if (!chatInput.value.trim() || !chatAgentId.value || chatLoading.value) return
  
  const msg = chatInput.value.trim()
  chatInput.value = ''
  chatMessages.value.push({ role: 'user', content: msg })
  chatLoading.value = true
  
  try {
    let assistantContent = ''
    for await (const event of streamChatWithAgent(chatAgentId.value, msg)) {
      if (event.type === 'text' || event.type === 'done') {
        assistantContent = event.content || assistantContent
      } else if (event.type === 'tool_call') {
        chatMessages.value.push({
          role: 'tool',
          content: `🔧 调用 ${event.tool}`,
          tool: event.tool,
        })
      } else if (event.type === 'tool_result') {
        chatMessages.value.push({
          role: 'tool',
          content: `✅ ${event.tool} 返回结果`,
          tool: event.tool,
        })
      } else if (event.type === 'error') {
        assistantContent = `❌ ${event.content}`
      }
    }
    if (assistantContent) {
      chatMessages.value.push({ role: 'assistant', content: assistantContent })
    }
  } catch (e: any) {
    chatMessages.value.push({ role: 'assistant', content: `❌ 错误: ${e.message}` })
  } finally {
    chatLoading.value = false
    await loadData()
  }
}

// ==================== Board (董事会) ====================

async function triggerBoard() {
  if (!boardTopic.value.trim() || boardLoading.value) return
  boardLoading.value = true
  boardResult.value = null
  try {
    const res = await boardDeliberate(boardTopic.value, boardSymbol.value)
    boardResult.value = (res as any).data || res as any
  } catch (e) {
    console.error('Board deliberate failed:', e)
  } finally {
    boardLoading.value = false
    await loadData()
  }
}

// Status helpers
function statusTag(status: string) {
  const map: Record<string, { type: string; label: string }> = {
    idle: { type: 'default', label: '待命' },
    active: { type: 'success', label: '运行中' },
    paused: { type: 'warning', label: '暂停' },
    error: { type: 'error', label: '错误' },
  }
  return map[status] || { type: 'default', label: status }
}
</script>

<template>
  <div class="max-w-7xl mx-auto space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-white flex items-center gap-3">
          🧠 Agent Hub
          <span
            class="text-sm px-3 py-1 rounded-full font-medium"
            :style="{ background: modeColor + '20', color: modeColor, border: '1px solid ' + modeColor + '40' }"
          >
            {{ modeLabel }}
          </span>
        </h1>
        <p class="text-sm text-gray-500 mt-1">智能体中枢 — 创建、管理和编排 AI 交易智能体</p>
      </div>
      <div class="flex gap-3">
        <NButton
          v-if="hubStatus && hubStatus.active_count >= 2"
          type="info"
          @click="showBoardModal = true"
        >
          <template #icon><NIcon><PeopleOutline /></NIcon></template>
          董事会辩论
        </NButton>
        <NButton type="primary" @click="showCreateModal = true">
          <template #icon><NIcon><AddOutline /></NIcon></template>
          新建智能体
        </NButton>
      </div>
    </div>

    <!-- Stats Cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4" v-if="hubStatus">
      <div class="p-4 rounded-xl border border-white/5 bg-white/[0.02]">
        <div class="text-xs text-gray-500">智能体总数</div>
        <div class="text-2xl font-bold text-white mt-1">{{ hubStatus.total_agents }}</div>
      </div>
      <div class="p-4 rounded-xl border border-white/5 bg-white/[0.02]">
        <div class="text-xs text-gray-500">运行中</div>
        <div class="text-2xl font-bold text-green-400 mt-1">{{ hubStatus.active_count }}</div>
      </div>
      <div class="p-4 rounded-xl border border-white/5 bg-white/[0.02]">
        <div class="text-xs text-gray-500">运行模式</div>
        <div class="text-lg font-bold mt-1" :style="{ color: modeColor }">{{ modeLabel }}</div>
      </div>
      <div class="p-4 rounded-xl border border-white/5 bg-white/[0.02]">
        <div class="text-xs text-gray-500">累计交易</div>
        <div class="text-2xl font-bold text-purple-400 mt-1">{{ agents.reduce((s, a) => s + a.total_trades, 0) }}</div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-20">
      <NSpin size="large" />
    </div>

    <!-- Empty State -->
    <div v-else-if="agents.length === 0" class="py-20">
      <NEmpty description="还没有创建任何智能体">
        <template #extra>
          <NButton type="primary" @click="showCreateModal = true">创建第一个智能体</NButton>
        </template>
      </NEmpty>
    </div>

    <!-- Agent Cards Grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div
        v-for="agent in agents"
        :key="agent.id"
        class="p-5 rounded-xl border transition-all duration-300 hover:shadow-lg"
        :style="{
          background: agent.is_active ? 'rgba(138,43,226,0.05)' : 'rgba(255,255,255,0.02)',
          borderColor: agent.is_active ? 'rgba(138,43,226,0.3)' : 'rgba(255,255,255,0.06)',
        }"
      >
        <!-- Header -->
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-3">
            <span class="text-2xl">{{ agent.avatar }}</span>
            <div>
              <div class="font-semibold text-white">{{ agent.name }}</div>
              <div class="text-xs text-gray-500">{{ agent.role }} · {{ agent.provider }}/{{ agent.model }}</div>
            </div>
          </div>
          <NTag
            :type="statusTag(agent.status).type as any"
            size="small"
            round
          >
            {{ statusTag(agent.status).label }}
          </NTag>
        </div>

        <!-- Stats -->
        <div class="grid grid-cols-3 gap-2 mb-3 text-center">
          <div class="p-2 rounded-lg bg-white/[0.03]">
            <div class="text-xs text-gray-500">运行次数</div>
            <div class="text-sm font-mono text-white">{{ agent.total_runs }}</div>
          </div>
          <div class="p-2 rounded-lg bg-white/[0.03]">
            <div class="text-xs text-gray-500">交易次数</div>
            <div class="text-sm font-mono text-purple-400">{{ agent.total_trades }}</div>
          </div>
          <div class="p-2 rounded-lg bg-white/[0.03]">
            <div class="text-xs text-gray-500">温度</div>
            <div class="text-sm font-mono text-gray-300">{{ agent.temperature }}</div>
          </div>
        </div>

        <!-- Error display -->
        <div v-if="agent.last_error" class="text-xs text-red-400 mb-3 p-2 rounded bg-red-500/10 truncate">
          ❌ {{ agent.last_error }}
        </div>

        <!-- Actions -->
        <div class="flex gap-2">
          <NButton
            v-if="!agent.is_active"
            size="small" type="success" quaternary
            @click="handleControl(agent.id, 'start')"
          >
            <template #icon><NIcon><PlayOutline /></NIcon></template>
            启动
          </NButton>
          <NButton
            v-else
            size="small" type="warning" quaternary
            @click="handleControl(agent.id, 'stop')"
          >
            <template #icon><NIcon><StopOutline /></NIcon></template>
            停止
          </NButton>
          <NButton
            size="small" quaternary
            @click="handleControl(agent.id, 'run_once')"
          >
            <template #icon><NIcon><FlashOutline /></NIcon></template>
            单次
          </NButton>
          <NButton
            size="small" quaternary
            @click="openChat(agent)"
          >
            <template #icon><NIcon><ChatboxEllipsesOutline /></NIcon></template>
            对话
          </NButton>
          <NButton
            size="small" type="error" quaternary
            @click="handleDelete(agent.id)"
            class="ml-auto"
          >
            <template #icon><NIcon><TrashOutline /></NIcon></template>
          </NButton>
        </div>
      </div>
    </div>

    <!-- ==================== Create Modal ==================== -->
    <NModal v-model:show="showCreateModal" preset="card" title="✨ 创建智能体" style="max-width: 500px;">
      <div class="space-y-4">
        <div>
          <label class="text-xs text-gray-500 mb-1 block">名称</label>
          <NInput v-model:value="createForm.name" placeholder="e.g. Alpha 猎手" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="text-xs text-gray-500 mb-1 block">角色</label>
            <NSelect v-model:value="createForm.role" :options="roleOptions" />
          </div>
          <div>
            <label class="text-xs text-gray-500 mb-1 block">头像</label>
            <NSelect v-model:value="createForm.avatar" :options="avatarOptions" />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="text-xs text-gray-500 mb-1 block">AI 供应商</label>
            <NSelect v-model:value="createForm.provider" :options="providerOptions" />
          </div>
          <div>
            <label class="text-xs text-gray-500 mb-1 block">模型</label>
            <NInput v-model:value="createForm.model" placeholder="deepseek-chat" />
          </div>
        </div>
        <div>
          <label class="text-xs text-gray-500 mb-1 block">API Key (可选, 覆盖全局)</label>
          <NInput v-model:value="createForm.api_key" type="password" show-password-on="click" placeholder="留空则使用全局配置" />
        </div>
        <div>
          <label class="text-xs text-gray-500 mb-1 block">温度 ({{ createForm.temperature }})</label>
          <NSlider v-model:value="createForm.temperature" :min="0" :max="2" :step="0.1" />
        </div>
        <div>
          <label class="text-xs text-gray-500 mb-1 block">专属指令 (System Prompt)</label>
          <NInput v-model:value="createForm.system_prompt" type="textarea" :rows="3" placeholder="为这个智能体定制角色和策略偏好..." />
        </div>
      </div>
      <template #action>
        <div class="flex justify-end gap-3">
          <NButton @click="showCreateModal = false">取消</NButton>
          <NButton type="primary" @click="handleCreate" :disabled="!createForm.name">创建</NButton>
        </div>
      </template>
    </NModal>

    <!-- ==================== Chat Modal ==================== -->
    <NModal v-model:show="showChatModal" preset="card" title="💬 智能体对话" style="max-width: 700px; max-height: 80vh;">
      <div class="flex flex-col" style="height: 60vh;">
        <div class="flex-1 overflow-auto space-y-3 mb-3 p-3 rounded-lg" style="background: rgba(0,0,0,0.3);">
          <div
            v-for="(msg, i) in chatMessages"
            :key="i"
            class="p-3 rounded-lg text-sm"
            :class="{
              'bg-purple-500/10 ml-8': msg.role === 'user',
              'bg-white/5 mr-8': msg.role === 'assistant',
              'bg-blue-500/10 text-blue-300 text-xs': msg.role === 'tool',
            }"
          >
            <div class="text-xs text-gray-500 mb-1">
              {{ msg.role === 'user' ? '你' : msg.role === 'tool' ? '🔧 工具' : '🤖 AI' }}
            </div>
            <div class="whitespace-pre-wrap">{{ msg.content }}</div>
          </div>
          <div v-if="chatLoading" class="text-center py-4 text-gray-500">
            <NSpin size="small" /> AI 思考中...
          </div>
        </div>
        <div class="flex gap-2">
          <NInput
            v-model:value="chatInput"
            placeholder="输入指令..."
            @keyup.enter="sendChat"
            :disabled="chatLoading"
          />
          <NButton type="primary" @click="sendChat" :loading="chatLoading">发送</NButton>
        </div>
      </div>
    </NModal>

    <!-- ==================== Board Modal ==================== -->
    <NModal v-model:show="showBoardModal" preset="card" title="🏛️ 董事会辩论" style="max-width: 700px;">
      <div class="space-y-4">
        <div>
          <label class="text-xs text-gray-500 mb-1 block">辩论议题</label>
          <NInput v-model:value="boardTopic" placeholder="e.g. BTC 当前应该做多还是做空?" />
        </div>
        <div>
          <label class="text-xs text-gray-500 mb-1 block">交易对</label>
          <NInput v-model:value="boardSymbol" placeholder="BTCUSDT" />
        </div>
        <NButton type="primary" block @click="triggerBoard" :loading="boardLoading">
          开始辩论
        </NButton>

        <!-- Results -->
        <div v-if="boardResult" class="space-y-3 mt-4">
          <div class="text-sm font-semibold text-white">各方观点:</div>
          <div
            v-for="op in boardResult.opinions"
            :key="op.agent_id"
            class="p-3 rounded-lg border border-white/5 bg-white/[0.02]"
          >
            <div class="flex items-center gap-2 mb-1">
              <span>{{ op.avatar }}</span>
              <span class="font-medium text-white">{{ op.agent_name }}</span>
              <NTag
                :type="op.decision === 'open_long' ? 'success' : op.decision === 'open_short' ? 'error' : 'default'"
                size="small"
              >
                {{ op.decision === 'open_long' ? '做多' : op.decision === 'open_short' ? '做空' : '观望' }}
              </NTag>
              <span class="text-xs text-gray-500 ml-auto">信心: {{ (op.confidence * 100).toFixed(0) }}%</span>
            </div>
            <div class="text-xs text-gray-400">{{ op.reasoning }}</div>
          </div>

          <!-- Consensus -->
          <div class="p-4 rounded-xl border-2 border-purple-500/30 bg-purple-500/5">
            <div class="text-sm font-bold text-purple-400 mb-2">📊 投票共识</div>
            <div class="flex items-center gap-4">
              <NTag
                :type="boardResult.consensus.decision === 'open_long' ? 'success' : boardResult.consensus.decision === 'open_short' ? 'error' : 'default'"
                size="large"
              >
                {{ boardResult.consensus.decision === 'open_long' ? '✅ 做多' : boardResult.consensus.decision === 'open_short' ? '❌ 做空' : '⏸️ 观望' }}
              </NTag>
              <span class="text-sm text-gray-400">{{ boardResult.consensus.vote_count }}</span>
              <span class="text-sm text-gray-400">信心: {{ (boardResult.consensus.confidence * 100).toFixed(0) }}%</span>
            </div>
            <div v-if="boardResult.consensus.executed" class="mt-2 text-xs text-green-400">
              ✅ 已执行 (订单 #{{ boardResult.consensus.order_id }})
            </div>
          </div>
        </div>
      </div>
    </NModal>
  </div>
</template>
