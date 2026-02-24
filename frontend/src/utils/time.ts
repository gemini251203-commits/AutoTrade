/**
 * Time Utilities — 统一时间格式化（北京时间 UTC+8）
 * ===================================================
 * 后端存储 UTC，前端显示统一转为北京时间。
 * 所有页面共用这些函数，避免各页面重复实现。
 *
 * 关键: 后端返回的时间字符串不带 "Z" 后缀，
 * 例如 "2026-02-24T18:45:00"，JS 会当成本地时间解析。
 * toUTC() 确保无时区标记的字符串被正确当作 UTC 解析。
 */

const TIMEZONE = 'Asia/Shanghai'

/**
 * 确保 ISO 字符串被当作 UTC 解析
 * - 已含 Z / +xx:xx / -xx:xx → 原样返回
 * - 无时区信息 → 追加 "Z"
 */
function toUTC(iso: string): string {
  const s = iso.trim()
  // 已有时区标记 (Z, +xx:xx, -xx:xx)
  if (/Z$/i.test(s) || /[+-]\d{2}:\d{2}$/.test(s)) return s
  return s + 'Z'
}

/**
 * 格式化为北京时间: "M/D HH:mm"
 * 例: "2/25 02:30"
 */
export function formatDateBJ(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(toUTC(iso))
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
 * 例: "02:30"
 */
export function formatTimeBJ(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(toUTC(iso))
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
 * 例: "2026-02-25 02:30:45"
 */
export function formatFullBJ(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(toUTC(iso))
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
 * 例: "02-25 02:30"
 */
export function formatDateTimeBJ(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(toUTC(iso))
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
  const d = new Date(toUTC(iso))
  if (isNaN(d.getTime())) return '--'

  return d.toLocaleTimeString('zh-CN', {
    timeZone: TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}
