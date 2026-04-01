/**
 * Axios Request Utility
 * =====================
 * Configured axios instance with auth interceptors.
 * 
 * Features:
 * - Auto auth token injection
 * - Route-change request cancellation (prevents connection pool starvation)
 * - Token refresh on 401
 * 
 * Usage:
 *   import request from '@/utils/request'
 *   const data = await request.get('/wallet/balance')
 */

import axios, { type AxiosInstance, type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'

// Create axios instance
const request: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 15000,  // 15s (was 30s — shorter timeout prevents connection hogging)
  headers: {
    'Content-Type': 'application/json',
  },
})

// ============================================
// Route-Change Request Cancellation
// ============================================
// 浏览器限制同域名最多 6 个并发连接。
// 当页面切换时，旧页面的 pending 请求会占用连接，
// 导致新页面的请求排队等待 → 页面切换卡顿。
// 解决方案：路由切换时取消所有 pending 请求。

const _pendingControllers = new Set<AbortController>()

/** 取消所有正在进行的 API 请求（路由切换时调用） */
export function cancelAllPendingRequests() {
  _pendingControllers.forEach(c => c.abort())
  _pendingControllers.clear()
}

// ============================================
// Request Interceptor
// ============================================

/**
 * 从 localStorage 获取当前活动会话的 Token
 * 兼容多账户模式 (auth_sessions) 和旧模式 (token)
 */
export function getAuthToken(): string | null {
  try {
    // 1. 尝试从多账户模式获取
    const sessions = localStorage.getItem('auth_sessions')
    const activeIndex = localStorage.getItem('auth_active_index')
    
    if (sessions) {
      const parsed = JSON.parse(sessions)
      const index = activeIndex ? parseInt(activeIndex, 10) : 0
      const token = parsed[index]?.token
      if (token) return token
    }
    
    // 2. 兼容旧的单账户模式
    return localStorage.getItem('token')
  } catch (e) {
    console.error('[Request] Failed to get token:', e)
    return null
  }
}

request.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getAuthToken()
    
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    
    //  为每个请求绑定 AbortController（除非已有 signal）
    if (!config.signal) {
      const controller = new AbortController()
      config.signal = controller.signal
      ;(config as any)._abortController = controller
      _pendingControllers.add(controller)
    }
    
    return config
  },
  (error: AxiosError) => {
    return Promise.reject(error)
  }
)

// ============================================
// Response Interceptor
// ============================================

let isRefreshing = false
let pendingRequests: Array<(token: string) => void> = []

request.interceptors.response.use(
  (response) => {
    //  请求完成，从 pending 集合中移除
    const ctrl = (response.config as any)?._abortController as AbortController | undefined
    if (ctrl) _pendingControllers.delete(ctrl)
    return response
  },
  async (error: AxiosError) => {
    //  清理 pending controller
    const ctrl = (error.config as any)?._abortController as AbortController | undefined
    if (ctrl) _pendingControllers.delete(ctrl)
    
    //  被路由切换取消的请求 — 完全静默（不触发 catch）
    if (axios.isCancel(error) || error.code === 'ERR_CANCELED') {
      // 返回一个永远不 resolve 的 Promise，防止上层 catch 报错
      return new Promise(() => {})
    }
    
    const status = error.response?.status
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }
    
    // Handle 401 Unauthorized — 尝试刷新 token
    if (status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true
      
      // 获取 refresh token
      const sessions = localStorage.getItem('auth_sessions')
      const activeIndex = localStorage.getItem('auth_active_index')
      let refreshToken: string | null = null
      
      if (sessions) {
        try {
          const parsed = JSON.parse(sessions)
          const index = activeIndex ? parseInt(activeIndex, 10) : 0
          refreshToken = parsed[index]?.refreshToken || null
        } catch { /* ignore */ }
      }
      
      if (refreshToken) {
        if (!isRefreshing) {
          isRefreshing = true
          
          try {
            // 调用刷新接口
            const refreshResponse = await axios.post('/api/auth/refresh', {
              refresh_token: refreshToken,
            })
            
            const newToken = refreshResponse.data.access_token
            const newRefresh = refreshResponse.data.refresh_token
            
            // 更新 localStorage
            if (sessions) {
              const parsed = JSON.parse(sessions)
              const index = activeIndex ? parseInt(activeIndex, 10) : 0
              if (parsed[index]) {
                parsed[index].token = newToken
                if (newRefresh) parsed[index].refreshToken = newRefresh
                localStorage.setItem('auth_sessions', JSON.stringify(parsed))
              }
            }
            
            // 重试所有等待的请求
            pendingRequests.forEach(cb => cb(newToken))
            pendingRequests = []
            
            // 重试原始请求
            originalRequest.headers.Authorization = `Bearer ${newToken}`
            return request(originalRequest)
          } catch {
            // 刷新失败 → 登出
            pendingRequests = []
            performLogout()
          } finally {
            isRefreshing = false
          }
        } else {
          // 已经在刷新中，排队等待
          return new Promise((resolve) => {
            pendingRequests.push((newToken: string) => {
              originalRequest.headers.Authorization = `Bearer ${newToken}`
              resolve(request(originalRequest))
            })
          })
        }
      } else {
        // 没有 refresh token → 直接登出
        performLogout()
      }
    }
    
    // Handle other errors
    if (status === 403) {
      console.error('[Request] Forbidden')
    }
    
    if (status === 500) {
      console.error('[Request] Server error')
    }
    
    return Promise.reject(error)
  }
)

function performLogout() {
  console.warn('[Request] Token refresh failed, logging out...')
  localStorage.removeItem('token')
  try {
    const authStore = useAuthStore()
    authStore.logout()
  } catch { /* Store not initialized */ }
  router.push('/login')
}

export default request
