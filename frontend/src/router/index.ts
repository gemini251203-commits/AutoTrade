/**
 * Vue Router Configuration
 * ========================
 * Routes and navigation guards for auth protection.
 */

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// Lazy-load views
const Login = () => import('@/views/Login.vue')
const Dashboard = () => import('@/views/Dashboard.vue')
const Settings = () => import('@/views/Settings.vue')
const SignalAssistant = () => import('@/views/SignalAssistant.vue')
const Wallet = () => import('@/views/Wallet.vue')
const Admin = () => import('@/views/Admin.vue')
const StrategyManager = () => import('@/views/StrategyManager.vue')
const ChatAgent = () => import('@/views/ChatAgent.vue')
const TradeJournal = () => import('@/views/TradeJournal.vue')
const AutopilotDashboard = () => import('@/views/AutopilotDashboard.vue')


// Route definitions
const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard,
    meta: { requiresAuth: true },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: Settings,
    meta: { requiresAuth: true },
  },
  {
    path: '/signal',
    name: 'SignalAssistant',
    component: SignalAssistant,
    meta: { requiresAuth: true },
  },
  {
    path: '/wallet',
    name: 'Wallet',
    component: Wallet,
    meta: { requiresAuth: true },
  },
  {
    path: '/admin',
    name: 'Admin',
    component: Admin,
    meta: { requiresAuth: true },
  },
  {
    path: '/strategy',
    name: 'StrategyManager',
    component: StrategyManager,
    meta: { requiresAuth: true },
  },
  {
    path: '/chat',
    name: 'ChatAgent',
    component: ChatAgent,
    meta: { requiresAuth: true },
  },
  {
    path: '/journal',
    name: 'TradeJournal',
    component: TradeJournal,
    meta: { requiresAuth: true },
  },
  {
    path: '/autopilot',
    name: 'AutopilotDashboard',
    component: AutopilotDashboard,
    meta: { requiresAuth: true },
  },

  // Catch-all redirect to dashboard
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

// Create router
const router = createRouter({
  history: createWebHistory(),
  routes,
})

// ============================================
// Navigation Guards
// ============================================

// Track whether we've loaded from storage
let storageLoaded = false

router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()
  const requiresAuth = to.meta.requiresAuth !== false
  
  // Always ensure localStorage is loaded (sync, fast)
  if (!storageLoaded) {
    await authStore.initialize()
    storageLoaded = true
  }
  
  // Check authentication
  if (requiresAuth && !authStore.isAuthenticated) {
    // Not authenticated, redirect to login
    next({ name: 'Login' })
  } else if (to.name === 'Login' && authStore.isAuthenticated && !to.query.addAccount) {
    // Already authenticated and NOT adding account, redirect to dashboard
    next({ name: 'Dashboard' })
  } else {
    // Proceed normally
    next()
  }
})

export default router
