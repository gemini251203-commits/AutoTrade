<script setup lang="ts">
import { NButton, NIcon, NTooltip, NTag } from 'naive-ui'
import {
  PlayOutline, StopOutline, FlashOutline, CreateOutline, TrashOutline,
} from '@vicons/ionicons5'
import type { HubAgent, WakeConditionsResponse } from '@/api/hub'

const props = defineProps<{
  agent: HubAgent
  wakeConditions?: WakeConditionsResponse | null
}>()

const emit = defineEmits<{
  (e: 'control', id: number, action: string): void
  (e: 'edit', agent: HubAgent): void
  (e: 'delete', id: number): void
}>()

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

// Wake condition display helpers
function formatWakeRemaining(minutes: number): string {
  if (minutes <= 0) return '即将超时'
  if (minutes < 1) return '剩余 <1 分钟'
  return `剩余 ${Math.round(minutes)} 分钟`
}

function formatWakeCondition(cond: { type: string; symbol: string; value: number }): string {
  const sym = cond.symbol || '任意币种'
  if (cond.type === 'price_above') return `${sym} > ${cond.value.toLocaleString()}`
  if (cond.type === 'price_below') return `${sym} < ${cond.value.toLocaleString()}`
  if (cond.type === 'change_pct') return `${sym} 变化 ≥ ${cond.value}%`
  return `${cond.type}: ${cond.value}`
}
</script>

<template>
  <div
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
      <NTag v-if="agent.active_template_id" size="tiny" :bordered="false" style="background: rgba(168,85,247,0.12); color: #c084fc; font-size: 10px; height: 16px; padding: 0 4px;"> 模板</NTag>
      <span v-if="agent.last_run_at" class="ml-auto text-gray-600 truncate" style="max-width: 100px;">{{ new Date(agent.last_run_at).toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Shanghai' }) }}</span>
    </div>

    <!-- Error -->
    <div v-if="agent.last_error" class="text-[10px] text-red-400 mb-2 p-1.5 rounded bg-red-500/10 truncate">
      [ERR] {{ agent.last_error }}
    </div>

    <!-- 唤醒条件展示 -->
    <div
      v-if="wakeConditions?.has_conditions"
      class="text-[10px] mb-2 p-2 rounded space-y-1"
      style="background: rgba(59, 130, 246, 0.08); border: 1px solid rgba(59, 130, 246, 0.2);"
    >
      <!-- 标题行: 状态 + 剩余时间 -->
      <div class="flex items-center justify-between">
        <span class="flex items-center gap-1 text-blue-400">
          <span class="animate-pulse">◉</span>
          <span class="font-semibold">等待唤醒</span>
        </span>
        <span class="text-blue-500/60">
          {{ formatWakeRemaining(wakeConditions!.remaining_minutes) }}
        </span>
      </div>
      <!-- 逐条展示条件 -->
      <div
        v-for="(cond, ci) in wakeConditions!.conditions"
        :key="ci"
        class="flex items-center gap-1.5 text-blue-300 pl-3"
      >
        <span class="text-blue-500/50">{{ ci > 0 ? '或' : '┗' }}</span>
        <span v-if="cond.type === 'price_above'" class="text-green-400">▲</span>
        <span v-else-if="cond.type === 'price_below'" class="text-red-400">▼</span>
        <span v-else class="text-yellow-400"></span>
        <span>{{ formatWakeCondition(cond) }}</span>
      </div>
    </div>

    <!-- Actions -->
    <div class="flex gap-1.5">
      <NTooltip :delay="300" placement="bottom">
        <template #trigger>
          <NButton v-if="!agent.is_active" size="tiny" type="success" quaternary @click="emit('control', agent.id, 'start')">
            <template #icon><NIcon size="14"><PlayOutline /></NIcon></template>
          </NButton>
          <NButton v-else size="tiny" type="warning" quaternary @click="emit('control', agent.id, 'stop')">
            <template #icon><NIcon size="14"><StopOutline /></NIcon></template>
          </NButton>
        </template>
        {{ agent.is_active ? '停止' : '启动' }}
      </NTooltip>
      <NTooltip :delay="300" placement="bottom">
        <template #trigger>
          <NButton size="tiny" quaternary @click="emit('control', agent.id, 'run_once')">
            <template #icon><NIcon size="14"><FlashOutline /></NIcon></template>
          </NButton>
        </template>
        单次执行
      </NTooltip>
      <NTooltip :delay="300" placement="bottom">
        <template #trigger>
          <NButton size="tiny" quaternary @click="emit('edit', agent)">
            <template #icon><NIcon size="14"><CreateOutline /></NIcon></template>
          </NButton>
        </template>
        编辑
      </NTooltip>
      <NTooltip :delay="300" placement="bottom">
        <template #trigger>
          <NButton size="tiny" type="error" quaternary class="ml-auto" @click="emit('delete', agent.id)">
            <template #icon><NIcon size="14"><TrashOutline /></NIcon></template>
          </NButton>
        </template>
        删除
      </NTooltip>
    </div>
  </div>
</template>
