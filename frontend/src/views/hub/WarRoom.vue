<script setup lang="ts">
import { NButton, NIcon, NInput } from 'naive-ui'
import { TrashOutline } from '@vicons/ionicons5'

export interface WRMessage {
  id: number
  type: 'system' | 'ai_text' | 'tool_call' | 'tool_result' | 'tool_trace' | 'error' | 'opinion' | 'consensus'
  avatar?: string
  name?: string
  content: string
  meta?: any
  time: string
}

defineProps<{
  messages: WRMessage[]
  connectionStatus: 'connected' | 'reconnecting' | 'error'
  logSearchKeyword: string
  logSearchLoading: boolean
  logPage: number
  logHasMore: boolean
}>()

const emit = defineEmits<{
  (e: 'update:logSearchKeyword', value: string): void
  (e: 'search'): void
  (e: 'clearSearch'): void
  (e: 'clearLogs'): void
  (e: 'prevPage'): void
  (e: 'nextPage'): void
}>()
</script>

<template>
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
      <span class="text-[10px] text-gray-600 ml-auto font-mono">{{ messages.length }} events</span>
    </div>
    <!-- 搜索栏 -->
    <div class="flex items-center gap-2 px-3 py-1.5 border-b border-white/5" style="background: rgba(0,0,0,0.2);">
      <NInput
        :value="logSearchKeyword"
        @update:value="emit('update:logSearchKeyword', $event)"
        placeholder="搜索日志记录..."
        size="tiny"
        clearable
        @keyup.enter="emit('search')"
        @clear="emit('clearSearch')"
        class="flex-1"
        style="max-width: 300px;"
      />
      <NButton size="tiny" quaternary :loading="logSearchLoading" @click="emit('search')">
        查询
      </NButton>
      <NButton size="tiny" quaternary type="error" @click="emit('clearLogs')" style="margin-left: auto;">
        <template #icon><NIcon size="13"><TrashOutline /></NIcon></template>
        清空
      </NButton>
    </div>
    <!-- War Room Content -->
    <div class="flex-1 overflow-auto p-3 space-y-2 custom-scrollbar">
      <!-- Empty state -->
      <div v-if="messages.length === 0" class="h-full flex items-center justify-center">
        <div class="text-center text-gray-600">
          <div class="text-3xl mb-3 font-mono text-gray-700">[~]</div>
          <div class="text-sm">War Room</div>
          <div class="text-xs text-gray-700 mt-1">Send a command above to see real-time AI actions</div>
        </div>
      </div>

      <!-- Messages -->
      <div
        v-for="msg in messages"
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
            <span
              class="text-[10px] rounded-full px-2 py-0.5"
              :class="msg.meta?.decision?.includes('做多') ? 'bg-green-500/20 text-green-400' : msg.meta?.decision?.includes('做空') ? 'bg-red-500/20 text-red-400' : 'bg-gray-500/20 text-gray-400'"
            >
              {{ msg.meta?.decision }}
            </span>
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
              <span
                class="text-sm font-bold rounded-full px-4 py-1"
                :class="msg.meta?.decision === 'open_long' ? 'bg-green-500/20 text-green-400' : msg.meta?.decision === 'open_short' ? 'bg-red-500/20 text-red-400' : 'bg-gray-500/20 text-gray-400'"
              >
                {{ msg.meta?.decision === 'open_long' ? 'LONG' : msg.meta?.decision === 'open_short' ? 'SHORT' : 'HOLD' }}
              </span>
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
      <NButton size="tiny" quaternary :disabled="logPage <= 1" @click="emit('prevPage')">
        &lt; 上一页
      </NButton>
      <span>第 {{ logPage }} 页</span>
      <NButton size="tiny" quaternary :disabled="!logHasMore" @click="emit('nextPage')">
        下一页 &gt;
      </NButton>
    </div>
  </div>
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
