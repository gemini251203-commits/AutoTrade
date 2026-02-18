<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { NIcon, NSpin } from 'naive-ui'
import { LockClosedOutline, PersonOutline, LogInOutline, MailOutline, PersonAddOutline } from '@vicons/ionicons5'
import { useAuthStore } from '@/stores/auth'
import request from '@/utils/request'

const router = useRouter()
const authStore = useAuthStore()

// Mode: login or register
const mode = ref<'login' | 'register'>('login')

const username = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const showError = ref(false)
const errorMessage = ref('')
const loading = ref(false)

const isLogin = computed(() => mode.value === 'login')

function toggleMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  showError.value = false
  errorMessage.value = ''
}

async function handleLogin() {
  showError.value = false
  
  if (!username.value || !password.value) {
    showError.value = true
    errorMessage.value = '请输入用户名和密码'
    return
  }
  
  const success = await authStore.login(username.value, password.value)
  
  if (success) {
    router.push('/')
  } else {
    showError.value = true
    errorMessage.value = authStore.error || '登录失败'
  }
}

async function handleRegister() {
  showError.value = false
  
  if (!username.value || !email.value || !password.value) {
    showError.value = true
    errorMessage.value = '请填写所有必填项'
    return
  }
  
  if (password.value !== confirmPassword.value) {
    showError.value = true
    errorMessage.value = '两次密码输入不一致'
    return
  }
  
  if (password.value.length < 6) {
    showError.value = true
    errorMessage.value = '密码至少6个字符'
    return
  }
  
  loading.value = true
  
  try {
    await request.post('/auth/register', {
      username: username.value,
      email: email.value,
      password: password.value,
    })
    
    // 注册成功后自动登录
    const success = await authStore.login(username.value, password.value)
    if (success) {
      router.push('/')
    }
  } catch (err: any) {
    showError.value = true
    errorMessage.value = err.response?.data?.detail || '注册失败'
  } finally {
    loading.value = false
  }
}

function handleSubmit() {
  if (isLogin.value) {
    handleLogin()
  } else {
    handleRegister()
  }
}

// Handle Enter key
function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    handleSubmit()
  }
}
</script>

<template>
  <div 
    class="min-h-screen flex items-center justify-center p-4 relative overflow-hidden"
    style="background: black;"
  >
    <!-- Background Effects -->
    <div class="absolute inset-0 overflow-hidden pointer-events-none">
      <div 
        class="absolute top-0 left-1/4 w-[500px] h-[500px] rounded-full opacity-20 blur-[100px] animate-pulse"
        style="background: #8a2be2; animation-duration: 8s;"
      ></div>
      <div 
        class="absolute bottom-0 right-1/4 w-[600px] h-[600px] rounded-full opacity-10 blur-[120px] animate-pulse"
        style="background: #00e676; animation-duration: 12s; animation-delay: 2s;"
      ></div>
      
      <!-- Grid Mesh -->
      <div 
        class="absolute inset-0 opacity-[0.05]"
        style="
          background-image: linear-gradient(rgba(255, 255, 255, 0.1) 1px, transparent 1px),
                            linear-gradient(90deg, rgba(255, 255, 255, 0.1) 1px, transparent 1px);
          background-size: 40px 40px;
          mask-image: radial-gradient(circle at center, black 40%, transparent 100%);
          -webkit-mask-image: radial-gradient(circle at center, black 40%, transparent 100%);
        "
      ></div>
    </div>
    
    <!-- Login/Register Card -->
    <div 
      class="relative w-full max-w-md p-6 md:p-8 glass-panel-heavy rounded-2xl fade-in slide-up backdrop-blur-xl shadow-2xl"
      style="
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        border: 1px solid rgba(255, 255, 255, 0.08);
      "
    >
      <!-- Logo -->
      <div class="text-center mb-10">
        <div class="flex items-center justify-center gap-3 mb-3">
          <div 
            class="w-10 h-10 rounded-xl flex items-center justify-center shadow-lg transform rotate-3"
            style="background: linear-gradient(135deg, #8a2be2 0%, #6d28d9 100%); box-shadow: 0 0 20px rgba(138, 43, 226, 0.4);"
          >
            <NIcon size="24" color="white">
              <LogInOutline />
            </NIcon>
          </div>
          <span class="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-gray-400 tracking-tight">AutoTrade</span>
          <span 
            class="text-[10px] px-1.5 py-0.5 rounded border font-mono tracking-widest uppercase" 
            style="background: rgba(138, 43, 226, 0.1); border-color: rgba(138, 43, 226, 0.3); color: #d8b4fe;"
          >
            Pro
          </span>
        </div>
        <p class="text-sm text-gray-400 font-medium tracking-wide">AI DRIVEN TRADING TERMINAL</p>
      </div>
      
      <!-- Error Message -->
      <div 
        v-if="showError && errorMessage"
        class="mb-6 p-4 rounded-xl text-sm flex items-center gap-3 animate-shake"
        style="background: rgba(255, 23, 68, 0.1); border: 1px solid rgba(255, 23, 68, 0.2); color: #ff5252;"
      >
        <div class="w-1.5 h-1.5 rounded-full bg-red-500"></div>
        {{ errorMessage }}
      </div>
      
      <!-- Form -->
      <div class="space-y-5">
        <!-- Username -->
        <div class="group">
          <label class="block text-xs font-semibold text-gray-400 mb-2 ml-1 uppercase tracking-wider">Username</label>
          <div 
            class="flex items-center gap-3 rounded-xl px-4 py-3.5 transition-all duration-300 group-focus-within:bg-white/5"
            style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08);"
          >
            <NIcon size="20" style="color: #71717a; transition: color 0.3s;" class="group-focus-within:text-purple-400">
              <PersonOutline />
            </NIcon>
            <input
              v-model="username"
              type="text"
              placeholder="Enter your username"
              class="flex-1 bg-transparent text-white text-sm outline-none placeholder:text-gray-600 font-medium"
              @keydown="handleKeydown"
            />
          </div>
        </div>
        
        <!-- Email (Register only) -->
        <div v-if="!isLogin" class="group">
          <label class="block text-xs font-semibold text-gray-400 mb-2 ml-1 uppercase tracking-wider">Email</label>
          <div 
            class="flex items-center gap-3 rounded-xl px-4 py-3.5 transition-all duration-300 group-focus-within:bg-white/5"
            style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08);"
          >
            <NIcon size="20" style="color: #71717a; transition: color 0.3s;" class="group-focus-within:text-purple-400">
              <MailOutline />
            </NIcon>
            <input
              v-model="email"
              type="email"
              placeholder="Enter your email"
              class="flex-1 bg-transparent text-white text-sm outline-none placeholder:text-gray-600 font-medium"
              @keydown="handleKeydown"
            />
          </div>
        </div>
        
        <!-- Password -->
        <div class="group">
          <label class="block text-xs font-semibold text-gray-400 mb-2 ml-1 uppercase tracking-wider">Password</label>
          <div 
            class="flex items-center gap-3 rounded-xl px-4 py-3.5 transition-all duration-300 group-focus-within:bg-white/5"
            style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08);"
          >
            <NIcon size="20" style="color: #71717a; transition: color 0.3s;" class="group-focus-within:text-purple-400">
              <LockClosedOutline />
            </NIcon>
            <input
              v-model="password"
              type="password"
              placeholder="Enter your password"
              class="flex-1 bg-transparent text-white text-sm outline-none placeholder:text-gray-600 font-medium"
              @keydown="handleKeydown"
            />
          </div>
        </div>
        
        <!-- Confirm Password (Register only) -->
        <div v-if="!isLogin" class="group">
          <label class="block text-xs font-semibold text-gray-400 mb-2 ml-1 uppercase tracking-wider">Confirm Password</label>
          <div 
            class="flex items-center gap-3 rounded-xl px-4 py-3.5 transition-all duration-300 group-focus-within:bg-white/5"
            style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08);"
          >
            <NIcon size="20" style="color: #71717a; transition: color 0.3s;" class="group-focus-within:text-purple-400">
              <LockClosedOutline />
            </NIcon>
            <input
              v-model="confirmPassword"
              type="password"
              placeholder="Confirm your password"
              class="flex-1 bg-transparent text-white text-sm outline-none placeholder:text-gray-600 font-medium"
              @keydown="handleKeydown"
            />
          </div>
        </div>
        
        <!-- Submit Button -->
        <button
          @click="handleSubmit"
          :disabled="authStore.loading || loading"
          class="w-full py-4 rounded-xl font-bold text-white flex items-center justify-center gap-2 transition-all mt-8 relative overflow-hidden group"
          :style="{
            background: (authStore.loading || loading) ? '#3f3f46' : 'linear-gradient(135deg, #8a2be2 0%, #7c3aed 100%)',
            boxShadow: (authStore.loading || loading) ? 'none' : '0 10px 30px -10px rgba(138, 43, 226, 0.6)',
            cursor: (authStore.loading || loading) ? 'not-allowed' : 'pointer',
            opacity: (authStore.loading || loading) ? '0.7' : '1',
          }"
        >
          <!-- Shiny Effect -->
          <div class="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-1000"></div>
          
          <NSpin v-if="authStore.loading || loading" size="small" stroke="#ffffff" />
          <template v-else>
            <span class="tracking-wide">{{ isLogin ? 'LOGIN' : 'CREATE ACCOUNT' }}</span>
            <NIcon size="18" class="group-hover:translate-x-1 transition-transform">
              <component :is="isLogin ? LogInOutline : PersonAddOutline" />
            </NIcon>
          </template>
        </button>
      </div>
      
      <!-- Toggle Mode -->
      <div class="mt-8 text-center">
        <button 
          @click="toggleMode"
          class="text-sm text-gray-500 hover:text-white transition-colors duration-300 flex items-center justify-center gap-2 mx-auto"
        >
          {{ isLogin ? 'New to AutoTrade?' : 'Already have an account?' }}
          <span class="text-purple-400 font-medium">{{ isLogin ? 'Register Now' : 'Sign In' }}</span>
        </button>
      </div>
      
      <!-- Footer -->
      <div v-if="isLogin" class="mt-8 pt-6 border-t border-white/5 text-center">
        <p class="text-[10px] text-gray-600 uppercase tracking-widest">
          Default Access: <span class="text-gray-400 font-mono bg-white/5 px-2 py-1 rounded">admin / admin</span>
        </p>
      </div>
    </div>
    
    <!-- Version -->
    <div class="fixed bottom-6 text-[10px] font-mono text-gray-700 tracking-widest opacity-50">
      v1.0.0 • SYSTEM STATUS: ONLINE
    </div>
  </div>
</template>

<style scoped>
/* Scoped Focus styles */
div:has(> input:focus) {
  border-color: #8a2be2 !important;
  background: rgba(138, 43, 226, 0.05) !important;
  box-shadow: 0 0 0 1px rgba(138, 43, 226, 0.2);
}

.animate-shake {
  animation: shake 0.5s cubic-bezier(.36,.07,.19,.97) both;
}

@keyframes shake {
  10%, 90% { transform: translate3d(-1px, 0, 0); }
  20%, 80% { transform: translate3d(2px, 0, 0); }
  30%, 50%, 70% { transform: translate3d(-4px, 0, 0); }
  40%, 60% { transform: translate3d(4px, 0, 0); }
}
</style>
