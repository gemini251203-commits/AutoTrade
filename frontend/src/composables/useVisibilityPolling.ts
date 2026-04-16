/**
 * useVisibilityPolling
 * ====================
 * 智能轮询 composable — 标签页不可见时自动暂停，可见时恢复并立即刷新。
 *
 * 用法:
 *   useVisibilityPolling(() => fetchData(), 5000)
 */

import { onMounted, onUnmounted } from 'vue'

export function useVisibilityPolling(
  callback: () => Promise<void> | void,
  intervalMs: number = 5000,
) {
  let timer: ReturnType<typeof setInterval> | null = null

  function start() {
    stop()
    timer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        callback()
      }
    }, intervalMs)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function onVisibilityChange() {
    if (document.visibilityState === 'visible') {
      callback() // 回到前台立即刷新一次
      start()
    } else {
      stop() // 后台暂停，释放连接池
    }
  }

  onMounted(() => {
    callback() // 首次挂载立即执行
    start()
    document.addEventListener('visibilitychange', onVisibilityChange)
  })

  onUnmounted(() => {
    stop()
    document.removeEventListener('visibilitychange', onVisibilityChange)
  })

  return { stop, start }
}
