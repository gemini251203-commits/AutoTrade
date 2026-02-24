/**
 * Time Utilities — 统一时间格式化（北京时间 UTC+8）
 * ===================================================
 * 后端存储 UTC，前端显示统一转为北京时间。
 * 所有页面共用这些函数，避免各页面重复实现。
 */

const TIMEZONE = 'Asia/Shanghai'

/**
 * 格式化为北京时间: "M/D HH:mm"
 * 例: "2/24 09:30"
 */
export function formatDateBJ(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '--'
  
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: TIMEZONE,
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(d)

  const month = parts.find(p => p.type === 'month')?.value
  const day = parts.find(p => p.type === 'day')?.value
  const hour = parts.find(p => p.type === 'hour')?.value
  const minute = parts.find(p => p.type === 'minute')?.value

  return `${month}/${day} ${hour}:${minute}`
}

/**
 * 格式化为北京时间: "HH:mm"
 * 例: "09:30"
 */
export function formatTimeBJ(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '--'

  return d.toLocaleTimeString('zh-CN', {
    timeZone: TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

/**
 * 格式化为北京时间完整格式: "YYYY-MM-DD HH:mm:ss"
 * 例: "2026-02-24 17:30:45"
 */
export function formatFullBJ(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '--'

  return d.toLocaleString('zh-CN', {
    timeZone: TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).replace(/\//g, '-')
}

/**
 * 格式化为北京时间: "MM-DD HH:mm"
 * 例: "02-24 17:30"
 */
export function formatDateTimeBJ(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '--'

  return d.toLocaleString('zh-CN', {
    timeZone: TIMEZONE,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).replace(/\//g, '-')
}

/**
 * 格式化为北京时间 HH:mm:ss (用于 PipelineMonitor 时间戳)
 */
export function formatHHMMSSBJ(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '--'

  return d.toLocaleTimeString('zh-CN', {
    timeZone: TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}
