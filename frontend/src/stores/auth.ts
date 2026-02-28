/**
 * Auth Store - Multi-Session Support
 * ====================================
 * Pinia store for multi-account authentication.
 * 
 * Features:
 * - Multiple simultaneous sessions
 * - Switch between accounts
 * - Add new account
 * - Logout current or all accounts
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import request from '@/utils/request'

// User interface - matches backend UserResponse exactly
interface User {
  id: number
  username: string
  email: string
  is_active: boolean
  is_superuser: boolean
}

// Session interface
interface Session {
  token: string
  refreshToken: string
  user: User
}

// Storage key
const SESSIONS_KEY = 'auth_sessions'
const ACTIVE_INDEX_KEY = 'auth_active_index'

export const useAuthStore = defineStore('auth', () => {
  // ============================================
  // State
  // ============================================
  
  // Multi-session support
  const sessions = ref<Session[]>([])
  const activeIndex = ref<number>(0)
  const loading = ref(false)
  const error = ref<string | null>(null)
  
  // ============================================
  // Getters
  // ============================================
  
  // Current active session
  const currentSession = computed(() => sessions.value[activeIndex.value] || null)
  const token = computed(() => currentSession.value?.token || null)
  const user = computed(() => currentSession.value?.user || null)
  const isAuthenticated = computed(() => !!token.value)
  const username = computed(() => user.value?.username || 'User')
  const isAdmin = computed(() => user.value?.is_superuser === true)
  
  // All sessions
  const allSessions = computed(() => sessions.value)
  const sessionCount = computed(() => sessions.value.length)
  
  // ============================================
  // Persistence
  // ============================================
  
  function saveToStorage() {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.value))
    localStorage.setItem(ACTIVE_INDEX_KEY, String(activeIndex.value))
  }
  
  function loadFromStorage() {
    try {
      const stored = localStorage.getItem(SESSIONS_KEY)
      if (stored) {
        sessions.value = JSON.parse(stored)
      }
      const storedIndex = localStorage.getItem(ACTIVE_INDEX_KEY)
      if (storedIndex !== null) {
        activeIndex.value = parseInt(storedIndex, 10)
      }
      // Validate index
      if (activeIndex.value >= sessions.value.length) {
        activeIndex.value = 0
      }
    } catch (e) {
      console.error('Failed to load auth state:', e)
      sessions.value = []
      activeIndex.value = 0
    }
  }
  
  // ============================================
  // Actions
  // ============================================
  
  /**
   * Login with username and password
   * Adds a new session or updates existing
   */
  async function login(username: string, password: string): Promise<boolean> {
    loading.value = true
    error.value = null
    
    try {
      // OAuth2 requires form-urlencoded data
      const formData = new URLSearchParams()
      formData.append('username', username)
      formData.append('password', password)
      
      const response = await fetch('/api/auth/token', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData,
      })
      
      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || 'Login failed')
      }
      
      const data = await response.json()
      const newToken = data.access_token
      const newRefreshToken = data.refresh_token || ''
      
      // Fetch user info with the NEW token
      // ⚠️ 必须用 raw fetch 而不是 request — 因为 request 的拦截器
      //    会用 localStorage 的旧 token 覆盖我们设置的新 token
      const userResponse = await fetch('/api/auth/me', {
        headers: {
          'Authorization': `Bearer ${newToken}`,
        },
      })
      
      if (!userResponse.ok) {
        throw new Error('Failed to fetch user info')
      }
      
      const userData: User = await userResponse.json()
      
      // Check if user already has a session
      const existingIndex = sessions.value.findIndex(s => s.user.id === userData.id)
      
      if (existingIndex >= 0) {
        // Update existing session
        sessions.value[existingIndex] = { token: newToken, refreshToken: newRefreshToken, user: userData }
        activeIndex.value = existingIndex
      } else {
        // Add new session
        sessions.value.push({ token: newToken, refreshToken: newRefreshToken, user: userData })
        activeIndex.value = sessions.value.length - 1
      }
      
      saveToStorage()
      return true
    } catch (e: any) {
      error.value = e.message || 'Login failed'
      return false
    } finally {
      loading.value = false
    }
  }
  
  /**
   * Switch to a different account
   */
  function switchAccount(index: number) {
    if (index >= 0 && index < sessions.value.length) {
      activeIndex.value = index
      saveToStorage()
    }
  }
  
  /**
   * Logout current account only
   */
  function logoutCurrent() {
    if (sessions.value.length === 0) return
    
    sessions.value.splice(activeIndex.value, 1)
    
    // Adjust active index
    if (activeIndex.value >= sessions.value.length) {
      activeIndex.value = Math.max(0, sessions.value.length - 1)
    }
    
    saveToStorage()
  }
  
  /**
   * Logout all accounts
   */
  function logoutAll() {
    sessions.value = []
    activeIndex.value = 0
    localStorage.removeItem(SESSIONS_KEY)
    localStorage.removeItem(ACTIVE_INDEX_KEY)
  }
  
  /**
   * Legacy logout (for compatibility)
   */
  function logout() {
    logoutAll()
  }
  
  /**
   * Fetch current user info
   */
  async function fetchUser(): Promise<void> {
    if (!token.value) return
    
    try {
      const response = await request.get<User>('/auth/me')
      
      const userData = response.data
      
      // Update current session user info
      if (currentSession.value) {
        currentSession.value.user = userData
        saveToStorage()
      }
    } catch (e) {
      console.error('Failed to fetch user:', e)
    }
  }
  
  /**
   * Initialize auth state on app load
   */
  async function initialize(): Promise<void> {
    loadFromStorage()
    if (token.value) {
      await fetchUser()
    }
  }
  
  // ============================================
  // Token Refresh
  // ============================================
  
  /**
   * Refresh access token using refresh token
   * 自动续期，无需重新登录
   */
  async function refreshAccessToken(): Promise<boolean> {
    const session = currentSession.value
    if (!session || !session.refreshToken) return false
    
    try {
      const response = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: session.refreshToken }),
      })
      
      if (!response.ok) return false
      
      const data = await response.json()
      // 更新当前会话的 token
      sessions.value[activeIndex.value] = {
        ...session,
        token: data.access_token,
        refreshToken: data.refresh_token || session.refreshToken,
      }
      saveToStorage()
      return true
    } catch {
      return false
    }
  }
  
  // ============================================
  // Return
  // ============================================
  
  return {
    // State
    sessions,
    activeIndex,
    loading,
    error,
    
    // Getters
    currentSession,
    token,
    user,
    isAuthenticated,
    username,
    isAdmin,
    allSessions,
    sessionCount,
    
    // Actions
    login,
    logout,
    logoutCurrent,
    logoutAll,
    switchAccount,
    fetchUser,
    initialize,
    refreshAccessToken,
  }
})
