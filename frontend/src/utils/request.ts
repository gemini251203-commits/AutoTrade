/**
 * Axios Request Utility
 * =====================
 * Configured axios instance with auth interceptors.
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
  baseURL: '/api',  // Vite proxy will forward to backend
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ============================================
// Request Interceptor
// ============================================

/**
 * 从 localStorage 获取当前活动会话的 Token
 * 兼容多账户模式 (auth_sessions) 和旧模式 (token)
 */
function getAuthToken(): string | null {
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
    // Return data directly
    return response
  },
  async (error: AxiosError) => {
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
