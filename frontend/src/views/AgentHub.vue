<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import MainLayout from '@/layouts/MainLayout.vue'
import {
  NButton, NModal, NInput, NSelect, NSlider, NTag, NSpin,
  NEmpty, NIcon, NTooltip, NScrollbar, NCheckbox, useMessage,
} from 'naive-ui'
import {
  AddOutline, TrashOutline, PlayOutline, StopOutline,
  FlashOutline, SendOutline, CreateOutline, DocumentTextOutline,
} from '@vicons/ionicons5'
import {
  listHubAgents, createHubAgent, updateHubAgent, deleteHubAgent,
  controlHubAgent, getHubStatus, boardDeliberate, streamChatWithAgent,
  getHubLogs, saveHubLog, triggerConsolidation, setSecretary, getSecretary, clearHubLogs,
  getMonthlyMinutes, listAllTools, getDailyRecap,
  type HubAgent, type HubStatus, type BoardResult,
  type HubAgentCreateRequest, type HubAgentUpdateRequest, type ToolInfo,
} from '@/api/hub'
import { CalendarOutline, ChevronBackOutline, ChevronForwardOutline } from '@vicons/ionicons5'

// ==================== State ====================

const agents = ref<HubAgent[]>([])
const hubStatus = ref<HubStatus | null>(null)
const loading = ref(false)

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
const warRoomRef = ref<HTMLElement | null>(null)
function scrollWarRoom() {
  nextTick(() => {
    if (warRoomRef.value) warRoomRef.value.scrollTop = 0
  })
}

// 编辑弹窗
const showEditModal = ref(false)
const editingAgent = ref<HubAgent | null>(null)
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
  if (allTools.value.length > 0) return // 已加载
  toolsLoading.value = true
  try {
    const res = await listAllTools()
    allTools.value = (res as any).data?.tools || (res as any).tools || []
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

// 工具权限: 切换单个工具
function toggleTool(name: string) {
  const form = editForm.value
  if (form.allowed_tools === null || form.allowed_tools === undefined) {
    // 从"全部"切换到"去掉这一个"
    form.allowed_tools = allTools.value.map(t => t.name).filter(n => n !== name)
  } else if (form.allowed_tools.includes(name)) {
    form.allowed_tools = form.allowed_tools.filter(n => n !== name)
  } else {
    form.allowed_tools = [...form.allowed_tools, name]
  }
}

// 工具权限: 切换整个分类
function toggleCategory(category: string) {
  const form = editForm.value
  const catTools = toolsByCategory.value[category]?.map(t => t.name) || []
  if (!catTools.length) return
  const allChecked = catTools.every(n => isToolChecked(n))
  if (allChecked) {
    // 取消全部
    if (form.allowed_tools === null || form.allowed_tools === undefined) {
      form.allowed_tools = allTools.value.map(t => t.name).filter(n => !catTools.includes(n))
    } else {
      form.allowed_tools = form.allowed_tools.filter(n => !catTools.includes(n))
    }
  } else {
    // 勾选全部
    if (form.allowed_tools === null || form.allowed_tools === undefined) return // 已是全部
    form.allowed_tools = [...new Set([...form.allowed_tools, ...catTools])]
  }
}

// 工具是否被勾选
function isToolChecked(name: string): boolean {
  const list = editForm.value.allowed_tools
  return list === null || list === undefined || list.includes(name)
}

// 分类是否全部勾选
function isCategoryAllChecked(category: string): boolean {
  const catTools = toolsByCategory.value[category]?.map(t => t.name) || []
  return catTools.every(n => isToolChecked(n))
}
function isCategoryPartialChecked(category: string): boolean {
  const catTools = toolsByCategory.value[category]?.map(t => t.name) || []
  const checkedCount = catTools.filter(n => isToolChecked(n)).length
  return checkedCount > 0 && checkedCount < catTools.length
}

// 全选 / 全不选
function selectAllTools() {
  editForm.value.allowed_tools = null // null = 全部
}
function deselectAllTools() {
  editForm.value.allowed_tools = []
}

// 轮询
let pollTimer: ReturnType<typeof setInterval> | null = null

interface WRMessage {
  id: number
  type: 'system' | 'ai_text' | 'tool_call' | 'tool_result' | 'tool_trace' | 'error' | 'opinion' | 'consensus'
  avatar?: string
  name?: string
  content: string
  meta?: any
  time: string
}

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

// Computed
const activeCount = computed(() => hubStatus.value?.active_count ?? 0)
const mode = computed(() => hubStatus.value?.mode ?? 'idle')

// 书记员下拉选项
const secretaryOptions = computed(() => {
  const opts: Array<{ label: string; value: number }> = []
  for (const a of agents.value) {
    opts.push({ label: `${a.name} (${a.model})`, value: a.id })
  }
  return opts
})

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

// ========== 日志格式化 ==========
const TOOL_LABELS: Record<string, string> = {
  get_balance: '查询余额',
  get_positions: '查询持仓',
  get_indicators: '获取行情',
  get_price: '查询价格',
  get_klines: '获取K线',
  get_funding_rate: '查询资金费率',
  get_market_sentiment: '市场情绪',
  place_order: '下单',
  close_position: '平仓',
  get_trade_journal: '查阅日志',
  manage_grid: '管理网格',
  analyze_trend_now: '趋势分析',
  search_historical_minutes: '检索纪要',
  get_market_overview: '市场概览',
  set_leverage: '设置杠杆',
  set_stop_loss: '设置止损',
  set_take_profit: '设置止盈',
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
      // 吞掉, 不显示
    } else {
      flushChain()
      result.push(m)
    }
  }
  flushChain()
  return result
}

// ==================== Data Loading ====================

async function loadData() {
  try {
    const [agentRes, statusRes, secRes] = await Promise.all([
      listHubAgents(), getHubStatus(), getSecretary().catch(() => null),
    ])
    agents.value = (agentRes as any).data?.agents || (agentRes as any).agents || []
    hubStatus.value = (statusRes as any).data || statusRes as any
    if (secRes) {
      secretaryAgentId.value = (secRes as any).data?.secretary_agent_id ?? (secRes as any).secretary_agent_id ?? null
    }
    // 连接成功
    connectionStatus.value = 'connected'
    pollFailCount = 0
  } catch (e) {
    pollFailCount++
    connectionStatus.value = pollFailCount >= 3 ? 'error' : 'reconnecting'
    console.error(`Failed to load hub data (attempt ${pollFailCount}):`, e)
  }
}
// ==================== 日志搜索 + 分页 ====================
const logSearchKeyword = ref('')
const logSearchLoading = ref(false)
const logPage = ref(1)
const logPageSize = 15
const logHasMore = ref(false)
const logTotal = ref(0)

/** 从 API 加载历史日志 */
async function loadWarRoomHistory(keyword?: string, page?: number) {
  try {
    logSearchLoading.value = true
    const p = page ?? logPage.value
    const params: any = { limit: logPageSize, offset: (p - 1) * logPageSize }
    if (keyword) params.keyword = keyword
    const res = await getHubLogs(params)
    const data = (res as any).data || res as any
    const logs = data?.logs || []
    logHasMore.value = data?.has_more ?? (logs.length >= logPageSize)
    logPage.value = p
    warRoomMessages.value = collapseToolLogs(logs.map((log: any) => wrMsg(
      log.log_type as WRMessage['type'],
      log.content,
      { name: log.agent_name, time: _utc2beijing(log.created_at) }
    )))
    scrollWarRoom()
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
  // 限制内存中消息数量，防止长时间运行 OOM
  if (warRoomMessages.value.length > 100) warRoomMessages.value.length = 100
  scrollWarRoom()
  // 异步保存，不阻塞 UI
  saveHubLog({
    agent_id: opts.agentId ?? null,
    agent_name: opts.agentName || opts.name || 'System',
    log_type: type,
    content,
  }).catch(() => {})
  return msg
}

/** 搜索日志 */
async function searchLogs() {
  await loadWarRoomHistory(logSearchKeyword.value.trim() || undefined)
}

onMounted(async () => {
  loading.value = true
  await Promise.all([loadData(), loadWarRoomHistory()])
  loading.value = false
  // 5秒轮询，确保状态及时更新
  pollTimer = setInterval(loadData, 10000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})



// ==================== 全局作战指示 ====================

async function sendGlobalCommand() {
  const cmd = globalCommand.value.trim()
  if (!cmd || globalCommandLoading.value || activeCount.value === 0) return

  globalCommand.value = ''
  globalCommandLoading.value = true

  if (mode.value === 'dictator' && activeAgentForDictator.value) {
    // 独裁者: SSE 对话
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
        } else if (event.type === 'tool_call') {
          // AI 用人话描述工具调用，这里不显示
        } else if (event.type === 'tool_result') {
          // AI 会用人话描述工具结果，这里不再显示原始 JSON
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
    system_prompt: '', temperature: 0.7, polling_interval: 5,
    allowed_tools: null,
  }
  showEditModal.value = true
  loadTools()
}

function openEdit(agent: HubAgent) {
  editingAgent.value = agent
  editForm.value = {
    id: agent.id,
    name: agent.name, role: agent.role, avatar: agent.avatar,
    provider: agent.provider, model: agent.model,
    api_base_url: agent.api_base_url, api_key: null,
    system_prompt: agent.system_prompt, temperature: agent.temperature,
    polling_interval: agent.polling_interval || 5,
    allowed_tools: agent.allowed_tools ? [...agent.allowed_tools] : null,
  }
  showEditModal.value = true
  loadTools()
}

async function handleSave() {
  if (!editForm.value.name) return
  try {
    if (editingAgent.value) {
      const data: HubAgentUpdateRequest = {}
      const fields: (keyof HubAgentUpdateRequest)[] = ['name', 'role', 'avatar', 'provider', 'model', 'api_base_url', 'api_key', 'system_prompt', 'temperature', 'polling_interval']
      for (const f of fields) {
        const v = (editForm.value as any)[f]
        if (v !== null && v !== undefined && v !== '') (data as any)[f] = v
      }
      // allowed_tools 始终显式传递（null = 全部，[] = 禁用，[...] = 指定）
      data.allowed_tools = editForm.value.allowed_tools
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
      pushAndSave('system', `[STARTED] ${agent?.name || `Agent #${id}`} activated`)
    } else if (action === 'stop') {
      pushAndSave('system', `[STOPPED] Agent #${id} deactivated`)
    } else if (action === 'run_once') {
      const agent = agents.value.find(a => a.id === id)
      if (!agent) return
      pushAndSave('system', `[TRIGGER] ${agent.name} 单次执行...`, { agentId: agent.id, agentName: agent.name })
      // 走 SSE 流式路径，实时显示思考过程
      try {
        const cyclePrompt = '轮到你值班了。看看现在市场什么情况，有没有机会，自己判断要不要动。'
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
          } else if (event.type === 'tool_call') {
            // AI 用人话描述工具调用，这里不显示
          } else if (event.type === 'tool_result') {
            // AI 会用人话描述工具结果，这里不再显示原始 JSON
          } else if (event.type === 'error') {
            warRoomMessages.value.push(wrMsg('error', event.content || '未知错误'))
          }
          scrollWarRoom()
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

// 立刻生成今日复盘
async function handleConsolidate() {
  consolidating.value = true
  warRoomMessages.value.push(wrMsg('system', '[System] 正在生成今日《董事会纪要》...', { name: 'System' }))
  scrollWarRoom()
  try {
    const res = await triggerConsolidation()
    const data = res.data || res
    const text = `[今日董事会纪要] (重要性: ${data.importance}/10)\n\n${data.summary}\n\n[核心教训]: ${data.key_lessons}`
    warRoomMessages.value.push(wrMsg('ai_text', text, { name: '书记员', avatar: 'BRAIN' }))
    // 保存到日志
    try { await saveHubLog({ agent_name: '书记员', log_type: 'ai_text', content: text }) } catch {}
  } catch (e: any) {
    warRoomMessages.value.push(wrMsg('error', `纪要生成失败: ${e?.message || e}`, { name: 'System' }))
  } finally {
    consolidating.value = false
    scrollWarRoom()
  }
}

// 清空 War Room 日志
async function handleClearLogs() {
  try {
    await clearHubLogs()
    warRoomMessages.value = []
  } catch (e: any) {
    console.error('clear logs failed', e)
  }
}

// 切换书记员
async function handleSecretaryChange(val: number | null) {
  secretaryAgentId.value = val
  try {
    await setSecretary(val)
    const name = agents.value.find(a => a.id === val)?.name || '系统默认'
    warRoomMessages.value.push(wrMsg('system', `首席书记员已切换为: ${name}`, { name: 'System' }))
    scrollWarRoom()
  } catch (e: any) {
    console.error('set secretary failed', e)
  }
}

// ==================== 历史纪要日历 ====================
interface MinutesEntry {
  id: number; date: string; summary: string; key_lessons: string
  importance: number; trade_count: number; pnl_total: number
}
const showMinutesModal = ref(false)
const minutesLoading = ref(false)
const minutesData = ref<MinutesEntry[]>([])
const calYear = ref(new Date().getFullYear())
const calMonth = ref(new Date().getMonth() + 1) // 1-12
const selectedMinute = ref<MinutesEntry | null>(null)

const calMonthLabel = computed(() => `${calYear.value} 年 ${calMonth.value} 月`)

// 日历网格生成
const calendarWeeks = computed(() => {
  const y = calYear.value, m = calMonth.value
  const firstDay = new Date(y, m - 1, 1)
  const daysInMonth = new Date(y, m, 0).getDate()
  const startDow = firstDay.getDay()  // 0=Sun
  const weeks: (number | null)[][] = []
  let week: (number | null)[] = Array(startDow).fill(null)
  for (let d = 1; d <= daysInMonth; d++) {
    week.push(d)
    if (week.length === 7) { weeks.push(week); week = [] }
  }
  if (week.length > 0) {
    while (week.length < 7) week.push(null)
    weeks.push(week)
  }
  return weeks
})

// 日期 -> 纪要 map
const minutesMap = computed(() => {
  const map: Record<string, MinutesEntry> = {}
  for (const m of minutesData.value) { map[m.date] = m }
  return map
})

function dateStr(day: number): string {
  return `${calYear.value}-${String(calMonth.value).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

async function openMinutesCalendar() {
  // 用北京时间的当前月份
  const now = new Date()
  const bjNow = new Date(now.getTime() + 8 * 3600000)
  calYear.value = bjNow.getUTCFullYear()
  calMonth.value = bjNow.getUTCMonth() + 1
  showMinutesModal.value = true
  selectedMinute.value = null
  await fetchMinutesMonth()
}

async function fetchMinutesMonth() {
  minutesLoading.value = true
  try {
    const res = await getMonthlyMinutes(calYear.value, calMonth.value)
    minutesData.value = (res as any).data?.minutes || (res as any).minutes || []
  } catch (e) {
    console.error('fetch minutes failed', e)
    minutesData.value = []
  } finally {
    minutesLoading.value = false
  }
}

async function calPrev() {
  if (calMonth.value === 1) { calYear.value--; calMonth.value = 12 }
  else { calMonth.value-- }
  selectedMinute.value = null
  await fetchMinutesMonth()
}

async function calNext() {
  if (calMonth.value === 12) { calYear.value++; calMonth.value = 1 }
  else { calMonth.value++ }
  selectedMinute.value = null
  await fetchMinutesMonth()
}

function selectDay(day: number | null) {
  if (!day) return
  const key = dateStr(day)
  selectedMinute.value = minutesMap.value[key] || null
}

// ==================== 每日复盘一键导出 ====================
const recapExporting = ref(false)
const message = useMessage()

async function exportDailyRecap(date: string) {
  recapExporting.value = true
  try {
    const markdown = await getDailyRecap(date)
    await navigator.clipboard.writeText(markdown)
    message.success('复盘素材已复制到剪贴板，可直接粘贴给 ChatGPT')
  } catch (e: any) {
    message.error(`导出失败: ${e?.message || e}`)
  } finally {
    recapExporting.value = false
  }
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
      <div class="flex-1 flex flex-col min-h-0 min-w-0 rounded-xl border border-white/5 overflow-hidden" style="background: rgba(0,0,0,0.4);">
        <!-- War Room Header -->
        <div class="flex items-center gap-2 px-4 py-2.5 border-b border-white/5" style="background: rgba(0,0,0,0.3);">
          <span class="text-green-400 text-xs font-mono animate-pulse">●</span>
          <span class="text-xs font-semibold text-gray-300 tracking-wider font-mono">WAR ROOM CONSOLE</span>
          <span
            class="ml-2 inline-block w-2 h-2 rounded-full"
            :class="{
              'bg-green-400 animate-pulse': connectionStatus === 'connected',
              'bg-yellow-400 animate-pulse': connectionStatus === 'reconnecting',
              'bg-red-500': connectionStatus === 'error',
            }"
            :title="connectionStatus === 'connected' ? 'Connected' : connectionStatus === 'reconnecting' ? 'Reconnecting...' : 'Disconnected'"
          />
          <span class="text-[10px] font-mono ml-1" :class="{
            'text-green-500': connectionStatus === 'connected',
            'text-yellow-500': connectionStatus === 'reconnecting',
            'text-red-500': connectionStatus === 'error',
          }">{{ connectionStatus === 'connected' ? 'Live' : connectionStatus === 'reconnecting' ? 'Reconnecting' : 'Offline' }}</span>
          <span class="text-[10px] text-gray-600 ml-auto font-mono">{{ warRoomMessages.length }} events</span>
        </div>
        <!-- 搜索栏 -->
        <div class="flex items-center gap-2 px-3 py-1.5 border-b border-white/5" style="background: rgba(0,0,0,0.2);">
          <NInput
            v-model:value="logSearchKeyword"
            placeholder="搜索日志记录..."
            size="tiny"
            clearable
            @keyup.enter="searchLogs"
            @clear="loadWarRoomHistory()"
            class="flex-1"
            style="max-width: 300px;"
          />
          <NButton size="tiny" quaternary :loading="logSearchLoading" @click="searchLogs">
            查询
          </NButton>
          <NButton size="tiny" quaternary type="error" @click="handleClearLogs" style="margin-left: auto;">
            <template #icon><NIcon size="13"><TrashOutline /></NIcon></template>
            清空
          </NButton>
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
            class="rounded-lg text-sm min-w-0"
            :class="{
              'px-3 py-1.5 text-xs': msg.type === 'system',
              'p-3': msg.type !== 'system' && msg.type !== 'consensus',
            }"
          >
            <!-- System message -->
            <div v-if="msg.type === 'system'" class="text-gray-500 font-mono text-[11px] flex items-center gap-2 min-w-0">
              <span class="text-gray-700 flex-shrink-0">{{ msg.time }}</span>
              <span class="break-all min-w-0">{{ msg.content }}</span>
            </div>

            <!-- AI Text -->
            <div v-else-if="msg.type === 'ai_text'" class="bg-white/[0.03] rounded-lg p-3">
              <div class="flex items-center gap-2 mb-1.5">
                <span class="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white" style="background: linear-gradient(135deg, #a855f7, #6366f1);">{{ msg.avatar?.charAt(0) || 'A' }}</span>
                <span class="text-xs font-semibold text-purple-300">{{ msg.name }}</span>
                <span class="text-[10px] text-gray-700 ml-auto font-mono">{{ msg.time }}</span>
              </div>
              <div class="text-gray-200 text-[13px] leading-relaxed whitespace-pre-wrap break-words" style="overflow-wrap: anywhere;">{{ msg.content }}</div>
            </div>

            <!-- Tool Trace (极简分隔线) -->
            <div v-else-if="msg.type === 'tool_trace'" class="flex items-center justify-center py-1.5 px-6">
              <div class="flex items-center gap-3 w-full text-[10px] text-gray-500 font-mono">
                <span class="flex-1 h-px" style="background: rgba(255,255,255,0.08);"></span>
                <span>执行了 {{ msg.content }} 项查询</span>
                <span class="flex-1 h-px" style="background: rgba(255,255,255,0.08);"></span>
              </div>
            </div>

            <!-- Tool Call (单条残留，极简) -->
            <div v-else-if="msg.type === 'tool_call'" class="flex items-center gap-2 px-3 py-0.5 text-[10px] text-gray-600 font-mono min-w-0">
              <span class="truncate">[调用] {{ msg.content }}</span>
            </div>

            <!-- Tool Result (隐藏) -->
            <template v-else-if="msg.type === 'tool_result'"></template>

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
        <!-- War Room Pagination Footer -->
        <div v-if="logPage > 1 || logHasMore" class="flex items-center justify-between px-4 py-1.5 border-t border-white/5 text-[10px] text-gray-600 font-mono" style="background: rgba(0,0,0,0.3);">
          <NButton size="tiny" quaternary :disabled="logPage <= 1" @click="logPrevPage">
            &lt; 上一页
          </NButton>
          <span>第 {{ logPage }} 页</span>
          <NButton size="tiny" quaternary :disabled="!logHasMore" @click="logNextPage">
            下一页 &gt;
          </NButton>
        </div>
      </div>
    </div>

    <!-- ========== 编辑 / 创建弹窗 ========== -->
    <NModal
      v-model:show="showEditModal"
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
              <span v-if="editingAgent?.has_api_key" class="text-green-500 ml-1">✓ 已保存</span>
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
              🔒 工具权限
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
          <NButton @click="showEditModal = false">取消</NButton>
          <NButton type="primary" @click="handleSave" :disabled="!editForm.name">
            {{ editingAgent ? '保存修改' : '创建' }}
          </NButton>
        </div>
      </template>
    </NModal>

    <!-- ========== 历史纪要日历 ========== -->
    <NModal
      v-model:show="showMinutesModal"
      preset="card"
      title="历史董事会纪要"
      style="max-width: 720px; max-height: 90vh;"
    >
      <div class="space-y-4">
        <!-- Calendar Header -->
        <div class="flex items-center justify-between">
          <button @click="calPrev" class="p-1 rounded hover:bg-white/10 text-gray-400 transition">
            <NIcon :component="ChevronBackOutline" :size="18" />
          </button>
          <span class="text-sm font-bold text-white">{{ calMonthLabel }}</span>
          <button @click="calNext" class="p-1 rounded hover:bg-white/10 text-gray-400 transition">
            <NIcon :component="ChevronForwardOutline" :size="18" />
          </button>
        </div>
        <!-- Calendar Grid -->
        <NSpin :show="minutesLoading">
          <table class="w-full border-collapse text-center">
            <thead>
              <tr>
                <th v-for="d in ['日','一','二','三','四','五','六']" :key="d" class="text-[10px] text-gray-600 py-1 font-normal">{{ d }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(week, wi) in calendarWeeks" :key="wi">
                <td
                  v-for="(day, di) in week"
                  :key="di"
                  class="py-1"
                >
                  <div
                    v-if="day"
                    @click="selectDay(day)"
                    class="mx-auto w-9 h-9 rounded-lg flex flex-col items-center justify-center cursor-pointer transition-all text-xs"
                    :class="{
                      'ring-1 ring-purple-500': selectedMinute?.date === dateStr(day),
                      'hover:bg-white/10': !minutesMap[dateStr(day)],
                    }"
                    :style="minutesMap[dateStr(day)] ? {
                      background: (minutesMap[dateStr(day)]?.pnl_total ?? 0) >= 0 ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
                      border: '1px solid ' + ((minutesMap[dateStr(day)]?.pnl_total ?? 0) >= 0 ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'),
                    } : {}"
                  >
                    <span class="text-gray-300">{{ day }}</span>
                    <span
                      v-if="minutesMap[dateStr(day)]"
                      class="text-[8px] font-mono"
                      :class="(minutesMap[dateStr(day)]?.pnl_total ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'"
                    >
                      {{ (minutesMap[dateStr(day)]?.pnl_total ?? 0) >= 0 ? '+' : '' }}{{ (minutesMap[dateStr(day)]?.pnl_total ?? 0).toFixed(1) }}
                    </span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </NSpin>
        <!-- Selected Day Detail -->
        <div v-if="selectedMinute" class="p-4 rounded-xl border border-white/10 bg-white/[0.03] space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-white">{{ selectedMinute.date }}</span>
            <div class="flex items-center gap-3 text-xs">
              <span class="text-gray-500">重要性: <b class="text-purple-400">{{ selectedMinute.importance }}/10</b></span>
              <span class="text-gray-500">交易: <b class="text-white">{{ selectedMinute.trade_count }}</b> 笔</span>
              <span :class="selectedMinute.pnl_total >= 0 ? 'text-green-400' : 'text-red-400'" class="font-mono font-bold">
                {{ selectedMinute.pnl_total >= 0 ? '+' : '' }}{{ selectedMinute.pnl_total.toFixed(2) }} USDT
              </span>
              <button
                class="px-2 py-0.5 rounded text-[11px] bg-blue-500/20 text-blue-300 border border-blue-500/30 hover:bg-blue-500/40 transition-colors"
                @click="exportDailyRecap(selectedMinute.date)"
                :disabled="recapExporting"
              >
                {{ recapExporting ? '导出中...' : '导出复盘' }}
              </button>
            </div>
          </div>
          <div class="text-[13px] text-gray-200 leading-relaxed whitespace-pre-wrap max-h-[320px] overflow-y-auto custom-scrollbar">{{ selectedMinute.summary }}</div>
          <div v-if="selectedMinute.key_lessons" class="p-2.5 rounded-lg bg-purple-500/10 border border-purple-500/20">
            <span class="text-[11px] text-purple-300 font-semibold">核心教训</span>
            <div class="text-xs text-gray-300 mt-1 max-h-[100px] overflow-y-auto custom-scrollbar">{{ selectedMinute.key_lessons }}</div>
          </div>
        </div>
        <div v-else class="text-center text-xs text-gray-600 py-6">
          点击日历上有色标的日期查看纪要
        </div>
      </div>
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
