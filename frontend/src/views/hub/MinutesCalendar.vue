<script setup lang="ts">
import { ref, computed } from 'vue'
import { NModal, NIcon, NSpin, useMessage } from 'naive-ui'
import { ChevronBackOutline, ChevronForwardOutline } from '@vicons/ionicons5'
import { getMonthlyMinutes, getDailyRecap } from '@/api/hub'
import request from '@/utils/request'

interface MinutesEntry {
  id: number; date: string; summary: string; key_lessons: string
  importance: number; trade_count: number; pnl_total: number
}

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void
}>()

const message = useMessage()
const minutesLoading = ref(false)
const minutesData = ref<MinutesEntry[]>([])
const calYear = ref(new Date().getFullYear())
const calMonth = ref(new Date().getMonth() + 1)
const selectedMinute = ref<MinutesEntry | null>(null)
const recapExporting = ref(false)

const calMonthLabel = computed(() => `${calYear.value} 年 ${calMonth.value} 月`)

// 日历网格生成
const calendarWeeks = computed(() => {
  const y = calYear.value, m = calMonth.value
  const firstDay = new Date(y, m - 1, 1)
  const daysInMonth = new Date(y, m, 0).getDate()
  const startDow = firstDay.getDay()
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

async function open() {
  const now = new Date()
  const bjNow = new Date(now.getTime() + 8 * 3600000)
  calYear.value = bjNow.getUTCFullYear()
  calMonth.value = bjNow.getUTCMonth() + 1
  selectedMinute.value = null
  await fetchMinutesMonth()
}

async function fetchMinutesMonth() {
  minutesLoading.value = true
  try {
    const [minutesRes, journalRes] = await Promise.all([
      getMonthlyMinutes(calYear.value, calMonth.value),
      request.get('/journal/', { params: { limit: 500, offset: 0 } }),
    ])
    const rawMinutes: MinutesEntry[] = (minutesRes as any).data?.minutes || (minutesRes as any).minutes || []

    // 从交易记录计算每日PnL
    const trades = journalRes.data?.items || []
    const tradePnlByDate: Record<string, number> = {}
    const tradeCountByDate: Record<string, number> = {}
    for (const m of trades) {
      if (!m.created_at || m.source === 'system') continue
      const t = new Date(m.created_at)
      const bj = new Date(t.getTime() + 8 * 3600000)
      const dk = `${bj.getUTCFullYear()}-${String(bj.getUTCMonth() + 1).padStart(2, '0')}-${String(bj.getUTCDate()).padStart(2, '0')}`
      tradePnlByDate[dk] = (tradePnlByDate[dk] || 0) + parseFloat(String(m.pnl_usdt || 0))
      tradeCountByDate[dk] = (tradeCountByDate[dk] || 0) + 1
    }

    // 用交易记录的 PnL 覆盖纪要的 pnl_total
    for (const entry of rawMinutes) {
      if (entry.date in tradePnlByDate) {
        entry.pnl_total = tradePnlByDate[entry.date]!
        entry.trade_count = tradeCountByDate[entry.date] ?? entry.trade_count
      }
    }

    // 对有交易但没纪要的日期，创建虚拟条目用于日历着色
    const existingDates = new Set(rawMinutes.map(m => m.date))
    for (const [date, pnl] of Object.entries(tradePnlByDate)) {
      if (!existingDates.has(date)) {
        rawMinutes.push({
          id: 0, date, summary: '', key_lessons: '',
          importance: 0, trade_count: tradeCountByDate[date] ?? 0, pnl_total: pnl,
        })
      }
    }

    minutesData.value = rawMinutes
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

async function exportDailyRecap(date: string) {
  recapExporting.value = true
  try {
    const markdown = await getDailyRecap(date)
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `复盘_${date}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    message.success('复盘素材已下载')
  } catch (e: any) {
    message.error(`导出失败: ${e?.message || e}`)
  } finally {
    recapExporting.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <NModal
    :show="show"
    @update:show="emit('update:show', $event)"
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
      <div v-if="selectedMinute" class="p-4 rounded-xl border border-white/10 bg-white/[0.03] space-y-3 max-h-[300px] overflow-y-auto custom-scrollbar">
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
