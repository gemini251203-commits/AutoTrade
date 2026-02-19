<script setup lang="ts">
/**
 * ChatAgent - AI 交易代理页面
 * ============================
 * 独立的 /chat 页面，用户通过对话指挥 AI 执行交易操作
 *
 * 功能:
 * - 多会话管理 (新建/切换/删除)
 * - 角色选择 (稳健/激进/量化/教练)
 * - 流式消息显示 (打字机效果)
 * - 工具调用状态展示
 * - Markdown 渲染
 */

import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useMessage } from 'naive-ui'
import {
  ChatboxEllipsesOutline,
  AddOutline,
  TrashOutline,
  SendOutline,
  PersonOutline,
  ChevronForwardOutline,
  ChevronBackOutline,
} from '@vicons/ionicons5'
import MainLayout from '@/layouts/MainLayout.vue'
import {
  getPersonas,
  createConversation,
  listConversations,
  deleteConversation,
  getMessages,
  sendMessage,
  type Persona,
  type Conversation,
  type ChatMessage,
  type SSEEvent,
} from '@/api/chat'
import { useAuthStore } from '@/stores/auth'

// ==================== State ====================

const authStore = useAuthStore()
const message = useMessage()

// 会话
const conversations = ref<Conversation[]>([])
const activeConversationId = ref<number | null>(null)
const personas = ref<Persona[]>([])
const selectedPersona = ref('conservative')

// 消息
const messages = ref<ChatMessage[]>([])
const streamingText = ref('')
const isStreaming = ref(false)
const toolStatus = ref<string | null>(null)

// UI
const inputText = ref('')
const chatContainerRef = ref<HTMLElement | null>(null)
const sidebarCollapsed = ref(false)
const loadingConversations = ref(false)
const loadingMessages = ref(false)
const mobileShowSidebar = ref(false)

// SSE 控制器
let abortController: AbortController | null = null



// ==================== Computed ====================

const activeConversation = computed(() =>
  conversations.value.find((c) => c.id === activeConversationId.value) || null
)

const activePersonaName = computed(() => {
  const conv = activeConversation.value
  if (!conv) return ''
  const p = personas.value.find((item: Persona) => item.id === conv.persona)
  return p?.name || conv.persona
})

const displayMessages = computed(() => {
  // 过滤掉 system 消息，只显示 user / assistant / tool
  return messages.value.filter((m) => m.role !== 'system')
})

// ==================== Lifecycle ====================

onMounted(async () => {
  await loadPersonas()
  await loadConversations()
})

// 自动滚动到底部
watch(
  [() => messages.value.length, streamingText],
  () => {
    nextTick(() => scrollToBottom())
  },
)



// ==================== API Methods ====================

async function loadPersonas() {
  try {
    personas.value = await getPersonas()
  } catch (e) {
    console.error('Failed to load personas:', e)
    // 使用默认值
    personas.value = [
      { id: 'conservative', name: '稳健交易员' },
      { id: 'aggressive', name: '激进交易员' },
      { id: 'quant', name: '量化分析师' },
      { id: 'mentor', name: '交易教练' },
    ]
  }
}

async function loadConversations() {
  loadingConversations.value = true
  try {
    conversations.value = await listConversations()
    // 如果有会话且没有选中的，自动选中第一个
    if (conversations.value.length > 0 && !activeConversationId.value) {
      const first = conversations.value[0]
      if (first) await selectConversation(first.id)
    }
  } catch (e) {
    console.error('Failed to load conversations:', e)
  } finally {
    loadingConversations.value = false
  }
}

async function handleCreateConversation() {
  try {
    const conv = await createConversation(selectedPersona.value)
    conversations.value.unshift(conv)
    await selectConversation(conv.id)
    message.success(`新会话已创建 (${getPersonaName(conv.persona)})`)
  } catch (e) {
    message.error('创建会话失败')
  }
}

async function selectConversation(id: number) {
  activeConversationId.value = id
  await loadMessages(id)
}

async function loadMessages(conversationId: number) {
  loadingMessages.value = true
  try {
    messages.value = await getMessages(conversationId)
  } catch (e) {
    console.error('Failed to load messages:', e)
    messages.value = []
  } finally {
    loadingMessages.value = false
  }
}

async function handleDeleteConversation(id: number) {
  if (!confirm('确定要删除这个会话及其所有消息吗？')) return
  
  try {
    await deleteConversation(id)
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (activeConversationId.value === id) {
      activeConversationId.value = conversations.value[0]?.id || null
      if (activeConversationId.value) {
        await loadMessages(activeConversationId.value)
      } else {
        messages.value = []
      }
    }
    message.success('会话已删除')
  } catch (e) {
    message.error('删除失败')
  }
}

async function handleSendMessage() {
  const text = inputText.value.trim()
  if (!text || isStreaming.value || !activeConversationId.value) return

  const token = authStore.token
  if (!token) {
    message.error('未登录')
    return
  }

  // 添加用户消息到 UI
  const userMsg: ChatMessage = {
    id: Date.now(),
    role: 'user',
    content: text,
    tool_name: null,
    tool_result: null,
    created_at: new Date().toISOString(),
  }
  messages.value.push(userMsg)
  inputText.value = ''
  isStreaming.value = true
  streamingText.value = ''
  toolStatus.value = null

  // 发送 SSE 请求
  abortController = sendMessage(
    activeConversationId.value,
    text,
    token,
    (event: SSEEvent) => {
      switch (event.type) {
        case 'text':
          streamingText.value += event.content || ''
          break
        case 'tool_call':
          toolStatus.value = `正在执行: ${event.tool}...`
          break
        case 'tool_result':
          toolStatus.value = null
          break
        case 'done':
          // 把流式文本添加为正式消息
          if (event.full_reply) {
            const aiMsg: ChatMessage = {
              id: Date.now() + 1,
              role: 'assistant',
              content: event.full_reply,
              tool_name: null,
              tool_result: null,
              created_at: new Date().toISOString(),
            }
            messages.value.push(aiMsg)
          }
          streamingText.value = ''
          isStreaming.value = false
          toolStatus.value = null
          // 更新会话列表标题
          loadConversations()
          break
        case 'error':
          message.error(event.message || 'AI 处理出错')
          isStreaming.value = false
          toolStatus.value = null
          streamingText.value = ''
          break
      }
    },
    (error: Error) => {
      message.error(`连接错误: ${error.message}`)
      isStreaming.value = false
      toolStatus.value = null
      streamingText.value = ''
    },
  )
}

function stopStreaming() {
  if (abortController) {
    abortController.abort()
    abortController = null
    isStreaming.value = false
    streamingText.value = ''
    toolStatus.value = null
  }
}

// ==================== Helpers ====================

function getPersonaName(id: string): string {
  return personas.value.find((p) => p.id === id)?.name || id
}

function scrollToBottom() {
  if (chatContainerRef.value) {
    chatContainerRef.value.scrollTop = chatContainerRef.value.scrollHeight
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSendMessage()
  }
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <MainLayout>
    <div class="chat-agent">
      <!-- 左侧: 会话列表 -->
      <aside :class="['sidebar', { collapsed: sidebarCollapsed, 'mobile-open': mobileShowSidebar }]">
        <div class="sidebar-header">
          <template v-if="!sidebarCollapsed">
            <h3>对话</h3>
          </template>
          <button
            class="collapse-btn"
            @click="sidebarCollapsed = !sidebarCollapsed"
          >
            <n-icon :component="sidebarCollapsed ? ChevronForwardOutline : ChevronBackOutline" />
          </button>
          <button class="mobile-close-btn" @click="mobileShowSidebar = false">✕</button>
        </div>

        <template v-if="!sidebarCollapsed">
          <!-- 新建会话 -->
          <div class="new-chat">
            <div class="new-chat-label">选择 AI 角色</div>
            <select
              v-model="selectedPersona"
              class="persona-select"
            >
              <option v-for="p in personas" :key="p.id" :value="p.id">
                {{ p.name }}
              </option>
            </select>
            <button
              class="create-chat-btn"
              @click="handleCreateConversation"
              :disabled="loadingConversations"
            >
              + 新建会话
            </button>
          </div>

          <!-- 会话列表标题 -->
          <div class="conv-list-header" v-if="conversations.length > 0">
            <span>历史会话 ({{ conversations.length }})</span>
          </div>

          <!-- 会话列表 -->
          <div class="conversation-list">
            <div
              v-for="conv in conversations"
              :key="conv.id"
              :class="['conversation-item', { active: conv.id === activeConversationId }]"
              @click="selectConversation(conv.id)"
            >
              <div class="conv-icon">
                <n-icon :component="ChatboxEllipsesOutline" :size="18" />
              </div>
              <div class="conv-info">
                <div class="conv-title">
                  <span v-if="conv.persona === 'autopilot'" class="autopilot-tag">[自动]</span>
                  {{ conv.title }}
                </div>
                <div class="conv-meta">
                  <span class="persona-badge">{{ getPersonaName(conv.persona) }}</span>
                </div>
              </div>
              <button
                class="conv-delete"
                @click.stop="handleDeleteConversation(conv.id)"
                title="删除此会话"
              >
                ✕
              </button>
            </div>
          </div>
        </template>
      </aside>

      <!-- 右侧: 聊天主区域 -->
      <main class="chat-main">
        <!-- 顶部栏 -->
        <div class="chat-header">
          <button class="mobile-menu-btn" @click="mobileShowSidebar = true">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="3" y1="6" x2="21" y2="6"/>
              <line x1="3" y1="12" x2="21" y2="12"/>
              <line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>
          <div class="header-info" v-if="activeConversation">
            <n-icon :component="PersonOutline" :size="20" />
            <span class="header-name">{{ activePersonaName }}</span>
            <n-tag :type="'info'" size="small" round>
              {{ activeConversation.title }}
            </n-tag>
          </div>
          <div class="header-spacer" v-else></div>

        </div>

        <!-- 空状态 -->
        <div v-if="!activeConversationId" class="empty-state">
          <div class="empty-icon">AI</div>
          <h2>AI 交易代理</h2>
          <p>在左侧选择一个 AI 角色, 点击「新建会话」开始对话</p>
          <div class="empty-roles">
            <div class="role-tag" v-for="p in personas" :key="p.id" @click="selectedPersona = p.id; handleCreateConversation()">
              {{ p.name }}
            </div>
          </div>
          <p class="empty-hint">AI 可以帮你查行情、下单、分析市场、查持仓</p>
        </div>

        <!-- 消息区域 -->
        <div v-else class="messages-container" ref="chatContainerRef">
          <div
            v-for="msg in displayMessages"
            :key="msg.id"
            :class="['message', msg.role]"
          >
            <div :class="['msg-avatar', msg.role === 'user' ? 'avatar-user' : 'avatar-ai']">
              {{ msg.role === 'user' ? 'U' : 'AI' }}
            </div>
            <div class="msg-bubble">
              <div class="msg-content" v-html="renderMarkdown(msg.content)"></div>
              <div class="msg-time">{{ formatTime(msg.created_at) }}</div>
            </div>
          </div>

          <!-- 流式消息 -->
          <div v-if="streamingText" class="message assistant">
            <div class="msg-avatar avatar-ai">AI</div>
            <div class="msg-bubble streaming">
              <div class="msg-content" v-html="renderMarkdown(streamingText)"></div>
              <div class="cursor-blink">|</div>
            </div>
          </div>

          <!-- 工具执行状态 -->
          <div v-if="toolStatus" class="tool-status">
            <n-spin size="small" />
            <span>{{ toolStatus }}</span>
          </div>

          <!-- 加载中 -->
          <div v-if="loadingMessages" class="loading-state">
            <n-spin size="medium" />
          </div>
        </div>

        <!-- 输入区域 -->
        <div class="input-area" v-if="activeConversationId">
          <div class="input-wrapper">
            <textarea
              v-model="inputText"
              placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
              @keydown="handleKeydown"
              :disabled="isStreaming"
              rows="1"
            />
            <button
              v-if="isStreaming"
              class="stop-btn"
              @click="stopStreaming"
            >
              ■ 停止
            </button>
            <button
              v-else
              class="send-btn"
              @click="handleSendMessage"
              :disabled="!inputText.trim()"
            >
              <n-icon :component="SendOutline" :size="20" />
            </button>
          </div>
          <div class="input-hint">
            AI 可以直接执行操作: 下单、平仓、查价格、查持仓、分析市场...
          </div>
        </div>
      </main>
    </div>
  </MainLayout>
</template>

<script lang="ts">
// 简易 Markdown 渲染 (避免引入额外依赖)
function renderMarkdown(text: string): string {
  if (!text) return ''
  return text
    // 代码块
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="lang-$1">$2</code></pre>')
    // 行内代码
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // 粗体
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // 斜体
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // 换行
    .replace(/\n/g, '<br>')
}
</script>

<style scoped>
/* ==================== Layout ==================== */
.chat-agent {
  display: flex;
  height: 100%;
  background: #0a0a0f;
  color: #e0e0e0;
  overflow: hidden;
}

/* Mobile-only buttons: hidden on desktop */
.mobile-menu-btn,
.mobile-close-btn {
  display: none;
}

/* ==================== Sidebar ==================== */
.sidebar {
  width: 280px;
  min-width: 280px;
  background: rgba(15, 15, 25, 0.6);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.sidebar.collapsed {
  width: 48px;
  min-width: 48px;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.sidebar-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  background: linear-gradient(135deg, #a78bfa, #818cf8);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.collapse-btn {
  background: none;
  border: none;
  color: #888;
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  transition: all 0.2s;
}

.collapse-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.new-chat {
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.persona-select {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid rgba(138, 43, 226, 0.4);
  border-radius: 8px;
  background: rgba(20, 20, 32, 0.8);
  color: #d8b4fe;
  font-size: 13px;
  cursor: pointer;
  outline: none;
  appearance: auto;
  -webkit-appearance: auto;
}

.persona-select:focus {
  border-color: rgba(138, 43, 226, 0.8);
  box-shadow: 0 0 8px rgba(138, 43, 226, 0.2);
}

.persona-select option {
  background: #1a1a2e;
  color: #e0e0e0;
}

.new-chat-label {
  font-size: 11px;
  color: #a78bfa;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.create-chat-btn {
  width: 100%;
  margin-top: 12px;
  padding: 10px 16px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(135deg, #8b5cf6, #6d28d9);
  color: white;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  letter-spacing: 0.5px;
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
}

.create-chat-btn:hover {
  box-shadow: 0 6px 16px rgba(139, 92, 246, 0.4);
  transform: translateY(-2px);
}

.create-chat-btn:active {
  transform: translateY(0);
}

.create-chat-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
  filter: grayscale(100%);
}

.conv-list-header {
  padding: 10px 16px 4px;
  font-size: 11px;
  color: #666;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.conversation-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 4px;
}

.conversation-item:hover {
  background: rgba(255, 255, 255, 0.06);
}

.conversation-item.active {
  background: linear-gradient(90deg, rgba(139, 92, 246, 0.1), rgba(139, 92, 246, 0.05));
  border: 1px solid rgba(139, 92, 246, 0.2);
  border-left: 3px solid #8b5cf6;
}

.conv-icon {
  color: #a78bfa;
  flex-shrink: 0;
}

.conv-info {
  flex: 1;
  min-width: 0;
}

.conv-title {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-meta {
  font-size: 11px;
  color: #888;
  margin-top: 2px;
}

.persona-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(167, 139, 250, 0.1);
  color: #a78bfa;
  font-size: 10px;
  font-weight: 500;
}

.conv-delete {
  background: none;
  border: none;
  color: #ef4444;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  opacity: 0.6;
  transition: all 0.2s;
  flex-shrink: 0;
  font-size: 14px;
  font-weight: 700;
  line-height: 1;
}

.conversation-item:hover .conv-delete {
  opacity: 1;
}

.conv-delete:hover {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

/* ==================== Chat Main ==================== */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.chat-header {
  padding: 12px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(15, 15, 25, 0.6);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.header-info {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #a78bfa;
}

.header-name {
  font-weight: 600;
  font-size: 14px;
  color: #e0e0e0;
}

/* ==================== Messages ==================== */
.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  scroll-behavior: smooth;
}

.message {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.message.user {
  flex-direction: row-reverse;
}

.msg-avatar {
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.avatar-user {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: white;
}

.avatar-ai {
  background: linear-gradient(135deg, #10b981, #059669);
  color: white;
}

.msg-bubble {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 16px;
  position: relative;
}

.message.user .msg-bubble {
  background: linear-gradient(135deg, #6366f1, #4f46e5);
  color: #fff;
  border-top-right-radius: 4px;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2);
}

.message.assistant .msg-bubble {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-top-left-radius: 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.msg-content {
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

.msg-content :deep(pre) {
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  margin: 8px 0;
}

.msg-content :deep(code) {
  font-family: 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
}

.msg-content :deep(strong) {
  color: #a78bfa;
}

.msg-time {
  font-size: 11px;
  color: #666;
  margin-top: 6px;
  text-align: right;
}

.message.user .msg-time {
  color: rgba(255, 255, 255, 0.5);
}

/* 流式动画 */
.streaming {
  border: 1px solid rgba(167, 139, 250, 0.3);
}

.cursor-blink {
  display: inline;
  animation: blink 1s infinite;
  color: #a78bfa;
  font-weight: bold;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* 工具状态 */
.tool-status {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  margin: 8px 48px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(167, 139, 250, 0.1), rgba(129, 140, 248, 0.05));
  border: 1px solid rgba(167, 139, 250, 0.2);
  font-size: 13px;
  color: #a78bfa;
  animation: fadeIn 0.3s ease;
}

/* ==================== Empty State ==================== */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #666;
}

.empty-icon {
  font-size: 64px;
  margin-bottom: 16px;
}

.empty-state h2 {
  margin: 0 0 8px;
  font-size: 24px;
  background: linear-gradient(135deg, #a78bfa, #818cf8);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.empty-state p {
  margin: 4px 0;
  font-size: 14px;
}

.empty-hint {
  color: #555;
  font-size: 13px !important;
}

.empty-roles {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0;
  justify-content: center;
}

.role-tag {
  padding: 8px 16px;
  border-radius: 20px;
  background: rgba(167, 139, 250, 0.1);
  border: 1px solid rgba(167, 139, 250, 0.25);
  color: #a78bfa;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.role-tag:hover {
  background: rgba(167, 139, 250, 0.2);
  border-color: rgba(167, 139, 250, 0.5);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(167, 139, 250, 0.2);
}

.loading-state {
  display: flex;
  justify-content: center;
  padding: 20px;
}

/* ==================== Input Area ==================== */
.input-area {
  padding: 16px 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(15, 15, 25, 0.8);
  backdrop-filter: blur(12px);
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  padding: 10px 16px;
  transition: border-color 0.2s;
}

.input-wrapper:focus-within {
  border-color: rgba(167, 139, 250, 0.4);
}

.input-wrapper textarea {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: #e0e0e0;
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  max-height: 120px;
  font-family: inherit;
}

.input-wrapper textarea::placeholder {
  color: #555;
}

.send-btn, .stop-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: 8px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.send-btn {
  color: #a78bfa;
}

.send-btn:hover:not(:disabled) {
  background: rgba(167, 139, 250, 0.15);
}

.send-btn:disabled {
  color: #444;
  cursor: not-allowed;
}

.stop-btn {
  color: #ef4444;
  font-size: 12px;
  font-weight: 600;
  border-radius: 8px;
  padding: 6px 12px;
}

.stop-btn:hover {
  background: rgba(239, 68, 68, 0.1);
}

.input-hint {
  font-size: 11px;
  color: #555;
  text-align: center;
  margin-top: 8px;
}

/* ==================== Scrollbar ==================== */
.messages-container::-webkit-scrollbar,
.conversation-list::-webkit-scrollbar {
  width: 4px;
}

.messages-container::-webkit-scrollbar-thumb,
.conversation-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
}

/* ==================== Responsive ==================== */
@media (max-width: 768px) {
  /* Mobile menu button (hidden on desktop) */
  .mobile-menu-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: none;
    border-radius: 8px;
    background: rgba(255,255,255,0.06);
    color: #a78bfa;
    cursor: pointer;
    margin-right: 8px;
    flex-shrink: 0;
  }
  .mobile-close-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border: none;
    border-radius: 8px;
    background: rgba(255,255,255,0.06);
    color: #9ca3af;
    cursor: pointer;
    font-size: 14px;
    margin-left: auto;
  }
  .sidebar {
    display: none;
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    z-index: 100;
    background: #0a0a0f;
    border: none;
  }
  .sidebar.mobile-open {
    display: flex;
  }
  .sidebar.collapsed {
    display: none;
  }
  .sidebar.collapsed.mobile-open {
    display: flex;
    width: 100vw;
    min-width: 100vw;
  }
  .chat-header {
    padding: 8px 12px;
  }
  .messages-container {
    padding: 10px;
  }
  .message {
    gap: 8px;
    margin-bottom: 12px;
  }
  .msg-avatar {
    width: 28px;
    height: 28px;
    font-size: 11px;
    border-radius: 8px;
  }
  .msg-bubble {
    max-width: 85%;
    padding: 10px 12px;
    border-radius: 12px;
  }
  .msg-content {
    font-size: 13px;
  }
  .input-area {
    padding: 8px 10px;
  }
  .input-wrapper {
    padding: 8px 12px;
    border-radius: 12px;
  }
  .input-hint {
    display: none;
  }
  .tool-status {
    margin: 8px 0;
    font-size: 12px;
  }
  .empty-icon {
    font-size: 40px;
  }
  .empty-state h2 {
    font-size: 18px;
  }
}

/* ==================== Autopilot ====================*/

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-spacer {
  flex: 1;
}

/* Avatar text styles */
.avatar-user {
  background: rgba(24, 144, 255, 0.2) !important;
  color: #1890ff !important;
  font-weight: 600;
  font-size: 12px !important;
}

.avatar-ai {
  background: rgba(82, 196, 26, 0.2) !important;
  color: #52c41a !important;
  font-weight: 600;
  font-size: 11px !important;
}

</style>

