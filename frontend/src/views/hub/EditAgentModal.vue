<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  NModal, NButton, NInput, NSelect, NSlider, NTag, NSpin, NCheckbox,
} from 'naive-ui'
import {
  listAllTools,
  type HubAgent, type HubAgentCreateRequest, type HubAgentUpdateRequest, type ToolInfo,
} from '@/api/hub'

const props = defineProps<{
  show: boolean
  editingAgent: HubAgent | null
}>()

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void
  (e: 'save', data: { form: HubAgentCreateRequest & { id?: number }; isEdit: boolean; promptChanged: boolean }): void
}>()

// 编辑表单
const editForm = ref<HubAgentCreateRequest & { id?: number }>({
  name: '', role: 'trader', avatar: 'BOT', provider: 'deepseek',
  model: 'deepseek-chat', api_base_url: null, api_key: null,
  system_prompt: '', temperature: 0.7, polling_interval: 5,
  allowed_tools: null,
})

// 工具权限
const allTools = ref<ToolInfo[]>([])
const toolsLoading = ref(false)

async function loadTools() {
  if (allTools.value.length > 0) return
  toolsLoading.value = true
  try {
    const res = await listAllTools()
    allTools.value = (res as any)?.tools || []
  } catch (e) {
    console.error('Failed to load tools:', e)
  } finally {
    toolsLoading.value = false
  }
}

// 工具按分类分组
const toolsByCategory = computed(() => {
  const map: Record<string, ToolInfo[]> = {}
  for (const t of allTools.value) {
    if (!map[t.category]) map[t.category] = []
    map[t.category]!.push(t)
  }
  return map
})

// 工具权限操作
function toggleTool(name: string) {
  const form = editForm.value
  if (form.allowed_tools === null || form.allowed_tools === undefined) {
    form.allowed_tools = allTools.value.map(t => t.name).filter(n => n !== name)
  } else if (form.allowed_tools.includes(name)) {
    form.allowed_tools = form.allowed_tools.filter(n => n !== name)
  } else {
    form.allowed_tools = [...form.allowed_tools, name]
  }
}

function toggleCategory(category: string) {
  const form = editForm.value
  const catTools = toolsByCategory.value[category]?.map(t => t.name) || []
  if (!catTools.length) return
  const allChecked = catTools.every(n => isToolChecked(n))
  if (allChecked) {
    if (form.allowed_tools === null || form.allowed_tools === undefined) {
      form.allowed_tools = allTools.value.map(t => t.name).filter(n => !catTools.includes(n))
    } else {
      form.allowed_tools = form.allowed_tools.filter(n => !catTools.includes(n))
    }
  } else {
    if (form.allowed_tools === null || form.allowed_tools === undefined) return
    form.allowed_tools = [...new Set([...form.allowed_tools, ...catTools])]
  }
}

function isToolChecked(name: string): boolean {
  const list = editForm.value.allowed_tools
  return list === null || list === undefined || list.includes(name)
}

function isCategoryAllChecked(category: string): boolean {
  const catTools = toolsByCategory.value[category]?.map(t => t.name) || []
  return catTools.every(n => isToolChecked(n))
}
function isCategoryPartialChecked(category: string): boolean {
  const catTools = toolsByCategory.value[category]?.map(t => t.name) || []
  const checkedCount = catTools.filter(n => isToolChecked(n)).length
  return checkedCount > 0 && checkedCount < catTools.length
}

function selectAllTools() {
  editForm.value.allowed_tools = null
}
function deselectAllTools() {
  editForm.value.allowed_tools = []
}

// Options
const roleOptions = [
  { label: 'Trader (交易员)', value: 'trader' },
  { label: 'Analyst (分析师)', value: 'analyst' },
  { label: 'Risk Advisor (风控顾问)', value: 'risk_advisor' },
]
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
  { label: 'Ollama (本地)', value: 'ollama' },
  { label: 'Custom (自定义)', value: 'custom' },
]
const pollingIntervalOptions = [
  { label: '1 分钟', value: 1 },
  { label: '5 分钟', value: 5 },
  { label: '15 分钟', value: 15 },
  { label: '30 分钟', value: 30 },
  { label: '60 分钟', value: 60 },
]

// 对外暴露的初始化方法
function openCreate() {
  editForm.value = {
    name: '', role: 'trader', avatar: 'BOT', provider: 'deepseek',
    model: 'deepseek-chat', api_base_url: null, api_key: null,
    system_prompt: '', temperature: 0.7, polling_interval: 5,
    allowed_tools: null,
  }
  loadTools()
}

function openEdit(agent: HubAgent) {
  editForm.value = {
    id: agent.id,
    name: agent.name, role: agent.role, avatar: agent.avatar,
    provider: agent.provider, model: agent.model,
    api_base_url: agent.api_base_url, api_key: null,
    system_prompt: agent.system_prompt, temperature: agent.temperature,
    polling_interval: agent.polling_interval || 5,
    allowed_tools: agent.allowed_tools ? [...agent.allowed_tools] : null,
  }
  loadTools()
}

function handleSave() {
  if (!editForm.value.name) return
  const promptChanged = props.editingAgent
    ? editForm.value.system_prompt !== props.editingAgent.system_prompt
    : false
  emit('save', {
    form: { ...editForm.value },
    isEdit: !!props.editingAgent,
    promptChanged,
  })
}

defineExpose({ openCreate, openEdit })
</script>

<template>
  <NModal
    :show="show"
    @update:show="emit('update:show', $event)"
    preset="card"
    :title="editingAgent ? `Edit ${editingAgent.name}` : 'Create Agent'"
    style="max-width: 760px; max-height: 90vh;"
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

      <!-- Row 2b: Base URL (仅 Custom / Ollama) -->
      <div v-if="editForm.provider === 'custom' || editForm.provider === 'ollama'" class="mt-2">
        <label class="text-[11px] text-gray-500 mb-1 block font-semibold">Base URL</label>
        <NInput v-model:value="editForm.api_base_url" placeholder="http://localhost:11434 或 https://your-api.com" />
      </div>

      <div class="grid grid-cols-3 gap-3">
        <div>
          <label class="text-[11px] text-gray-500 mb-1 block font-semibold">
            API Key <span class="text-gray-700">(可选，覆盖全局)</span>
            <span v-if="editingAgent?.has_api_key" class="text-green-500 ml-1"> 已保存</span>
          </label>
          <NInput v-model:value="editForm.api_key" type="password" show-password-on="click" :placeholder="editingAgent?.has_api_key ? '•••••• (已保存，留空不修改)' : '留空则使用全局配置'" />
        </div>
        <div>
          <label class="text-[11px] text-gray-500 mb-1 block font-semibold">温度 ({{ editForm.temperature }})</label>
          <NSlider v-model:value="editForm.temperature" :min="0" :max="2" :step="0.1" class="mt-2" />
        </div>
        <div>
          <label class="text-[11px] text-gray-500 mb-1 block font-semibold">轮询间隔</label>
          <NSelect v-model:value="editForm.polling_interval" :options="pollingIntervalOptions" />
        </div>
      </div>

      <!-- Row 4: System Prompt -->
      <div>
        <div class="flex items-center justify-between mb-1.5">
          <label class="text-[11px] text-gray-500 font-semibold">
            System Prompt (KPI)
            <span class="text-gray-700 font-normal ml-2">— 在这里写入角色定位、交易风格、绩效目标</span>
          </label>
          <router-link to="/prompts" class="text-[10px] text-purple-400 hover:text-purple-300 transition-colors flex items-center gap-1">
             提示词模板管理 →
          </router-link>
        </div>
        <div v-if="editingAgent?.active_template_id" class="mb-2 p-2 rounded-lg border border-purple-500/20 bg-purple-500/5 text-xs text-purple-300 flex items-center gap-2">
          <span></span>
          <span>此 Agent 已绑定提示词模板，下方内容为备用提示词。激活的模板优先使用。</span>
          <router-link to="/prompts" class="text-purple-400 hover:underline ml-auto">管理</router-link>
        </div>
        <div class="rounded-lg border border-white/10 overflow-hidden" style="background: rgba(0,0,0,0.3);">
          <NInput
            v-model:value="editForm.system_prompt"
            type="textarea"
            :autosize="{ minRows: 10, maxRows: 20 }"
            placeholder="在这里定义 AI 的角色和目标。例如:

你是我的专属交易员。
目标: 3天内赚 200 USDT。
风格: 稳健，不追高。
优先交易 BTC 和 ETH。"
            style="font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 12px; line-height: 1.6;"
          />
        </div>
      </div>

      <!-- Row 5: 工具权限 Checkbox 面板 -->
      <div>
        <div class="flex items-center justify-between mb-2">
          <label class="text-[11px] text-gray-500 font-semibold">
             工具权限
            <span class="text-gray-600 font-normal ml-1">勾选授权工具，未勾选工具不会发送给 AI</span>
          </label>
          <div class="flex items-center gap-2">
            <NButton size="tiny" quaternary @click="selectAllTools" class="!text-[10px] !text-blue-400">全选</NButton>
            <span class="text-gray-700">|</span>
            <NButton size="tiny" quaternary @click="deselectAllTools" class="!text-[10px] !text-gray-500">全不选</NButton>
            <NTag v-if="editForm.allowed_tools !== null && editForm.allowed_tools !== undefined" size="small" :bordered="false" style="background: rgba(99,102,241,0.15); color: #818cf8;">
              {{ editForm.allowed_tools.length }} / {{ allTools.length }}
            </NTag>
            <NTag v-else size="small" :bordered="false" style="background: rgba(34,197,94,0.15); color: #4ade80;">全部可用</NTag>
          </div>
        </div>

        <div v-if="toolsLoading" class="flex items-center justify-center py-6">
          <NSpin size="small" />
        </div>

        <div v-else class="rounded-lg border border-white/8 overflow-hidden" style="background: rgba(0,0,0,0.15); max-height: 320px; overflow-y: auto;">
          <div v-for="(tools, category) in toolsByCategory" :key="category">
            <!-- 分类头 -->
            <div
              class="flex items-center gap-2 px-3 py-1.5 cursor-pointer select-none"
              style="background: rgba(255,255,255,0.03); border-bottom: 1px solid rgba(255,255,255,0.04);"
              @click="toggleCategory(category as string)"
            >
              <NCheckbox
                :checked="isCategoryAllChecked(category as string)"
                :indeterminate="isCategoryPartialChecked(category as string)"
                @update:checked="toggleCategory(category as string)"
                @click.stop
              />
              <span class="text-[11px] font-semibold text-gray-300 tracking-wide">{{ category }}</span>
              <span class="text-[10px] text-gray-600 ml-auto">{{ tools.length }}工具</span>
            </div>
            <!-- 工具列表: 三列卡片式 -->
            <div class="grid grid-cols-3 gap-x-1 gap-y-0 px-2 py-1" style="border-bottom: 1px solid rgba(255,255,255,0.03);">
              <div
                v-for="tool in tools"
                :key="tool.name"
                class="flex items-center gap-1.5 py-1 px-1.5 rounded cursor-pointer transition-colors"
                :class="isToolChecked(tool.name) ? 'hover:bg-white/5' : 'opacity-50 hover:opacity-80 hover:bg-white/5'"
                @click="toggleTool(tool.name)"
              >
                <NCheckbox
                  :checked="isToolChecked(tool.name)"
                  @update:checked="toggleTool(tool.name)"
                  @click.stop
                  size="small"
                />
                <span
                  class="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  :style="{ background: tool.access_type === 'execute' ? '#f87171' : '#60a5fa' }"
                  :title="tool.access_type === 'execute' ? '执行类' : '只读类'"
                />
                <span class="text-[11px] text-gray-400 truncate" :title="tool.description">
                  {{ tool.description }}
                </span>
              </div>
            </div>
          </div>
        </div>
        <!-- 图例 -->
        <div class="flex items-center gap-4 mt-1.5 text-[10px] text-gray-600">
          <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-blue-400 inline-block"></span> 只读查询</span>
          <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-red-400 inline-block"></span> 执行操作</span>
        </div>
      </div>
    </div>

    <template #action>
      <div class="flex justify-end gap-3">
        <NButton @click="emit('update:show', false)">取消</NButton>
        <NButton type="primary" @click="handleSave" :disabled="!editForm.name">
          {{ editingAgent ? '保存修改' : '创建' }}
        </NButton>
      </div>
    </template>
  </NModal>
</template>
