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
  timeout: 15000,
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
    
    // 🔍 调试日志 - 生产环境可移除
    console.log('[Request] 🔑', config.method?.toUpperCase(), config.url, token ? `Token: ${token.slice(0, 20)}...` : 'No Token')
    
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

request.interceptors.response.use(
  (response) => {
    // Return data directly
    return response
  },
  (error: AxiosError) => {
    const status = error.response?.status
    
    // Handle 401 Unauthorized
    if (status === 401) {
      console.warn('[Request] Unauthorized, logging out...')
      
      // Clear token
      localStorage.removeItem('token')
      
      // Try to logout through store if available
      try {
        const authStore = useAuthStore()
        authStore.logout()
      } catch (e) {
        // Store not initialized, just redirect
      }
      
      // Redirect to login
      router.push('/login')
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

export default request
