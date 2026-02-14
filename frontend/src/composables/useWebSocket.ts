/**
 * useWebSocket Composable
 * ========================
 * 实时价格 WebSocket 连接管理
 * 
 * 功能:
 * - 自动重连 (指数退避)
 * - 心跳检测
 * - 响应式价格数据
 * - 自动清理
 * 
 * 用法:
 *   const { prices, isConnected, getPrice } = useWebSocket()
 *   const btcPrice = computed(() => getPrice('BTCUSDT'))
 */

import { ref, onUnmounted, readonly } from 'vue'

interface PriceUpdate {
  type: string
  prices: Record<string, string>
  timestamp: string
}

// 全局共享状态 (多组件共用一个连接)
const prices = ref<Record<string, number>>({})
const isConnected = ref(false)
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectAttempts = 0
let refCount = 0  // 引用计数，最后一个组件卸载时断开

const MAX_RECONNECT_ATTEMPTS = 10
const BASE_RECONNECT_DELAY = 1000  // 1秒

function getWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/ws/prices`
}

function connect() {
  if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) {
    return
  }

  try {
    ws = new WebSocket(getWsUrl())

    ws.onopen = () => {
      console.log('[WS] Connected')
      isConnected.value = true
      reconnectAttempts = 0
    }

    ws.onmessage = (event: MessageEvent) => {
      try {
        const data: PriceUpdate = JSON.parse(event.data)
        if (data.type === 'price_update' && data.prices) {
          // 更新所有价格
          const p = data.prices
          for (const symbol in p) {
            if (Object.prototype.hasOwnProperty.call(p, symbol)) {
              const val = p[symbol]
              if (val !== undefined) {
                prices.value[symbol] = parseFloat(val)
              }
            }
          }
        }
      } catch (e) {
        console.warn('[WS] Parse error:', e)
      }
    }

    ws.onclose = (event) => {
      console.log(`[WS] Disconnected (code=${event.code})`)
      isConnected.value = false
      ws = null
      
      // 只在还有组件使用时重连
      if (refCount > 0) {
        scheduleReconnect()
      }
    }

    ws.onerror = (error) => {
      console.warn('[WS] Error:', error)
    }
  } catch (e) {
    console.error('[WS] Connection failed:', e)
    scheduleReconnect()
  }
}

function scheduleReconnect() {
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    console.warn('[WS] Max reconnect attempts reached, stopping')
    return
  }

  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
  }

  // 指数退避: 1s, 2s, 4s, 8s, 16s, max 30s
  const delay = Math.min(BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttempts), 30000)
  reconnectAttempts++
  
  console.log(`[WS] Reconnecting in ${delay}ms (attempt ${reconnectAttempts})`)
  reconnectTimer = setTimeout(connect, delay)
}

function disconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (ws) {
    ws.close()
    ws = null
  }
  isConnected.value = false
}

/**
 * WebSocket 实时价格 composable
 * 
 * 多个组件可同时调用，共享一个 WebSocket 连接。
 * 最后一个组件卸载时自动断开。
 */
export function useWebSocket() {
  // 引用计数 +1
  refCount++
  
  // 首次使用时连接
  if (refCount === 1) {
    connect()
  }

  // 组件卸载时 -1
  onUnmounted(() => {
    refCount--
    if (refCount <= 0) {
      refCount = 0
      disconnect()
    }
  })

  /**
   * 获取指定交易对的最新价格
   */
  function getPrice(symbol: string): number {
    return prices.value[symbol] || 0
  }

  return {
    /** 所有交易对价格 (响应式) */
    prices: readonly(prices),
    /** WebSocket 连接状态 */
    isConnected: readonly(isConnected),
    /** 获取指定交易对价格 */
    getPrice,
  }
}
