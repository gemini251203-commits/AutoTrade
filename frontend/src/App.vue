<script setup lang="ts">
import { onMounted } from 'vue'
import { NConfigProvider, NMessageProvider, NDialogProvider, darkTheme, NGlobalStyle } from 'naive-ui'
import { useAuthStore } from './stores/auth'

// Initialize auth on app startup to restore session from localStorage
const authStore = useAuthStore()
onMounted(() => {
  authStore.initialize()
})

// Custom theme overrides — Professional Blue Finance Terminal
const themeOverrides = {
  common: {
    primaryColor: '#3b82f6', // Finance Blue
    primaryColorHover: '#60a5fa',
    primaryColorPressed: '#2563eb',
    primaryColorSuppl: '#3b82f6',
    successColor: '#22c55e',
    successColorHover: '#4ade80',
    warningColor: '#f59e0b',
    errorColor: '#ef4444',
    errorColorHover: '#f87171',
    textColor1: '#ffffff',
    textColor2: '#a1a1aa',
    textColor3: '#52525b',
    bodyColor: '#0f1117',
    cardColor: '#1a1d29',
    modalColor: '#1a1d29',
    popoverColor: '#1a1d29',
    borderRadius: '12px',
    borderColor: 'rgba(255, 255, 255, 0.08)',
    inputColor: 'rgba(255, 255, 255, 0.03)',
    inputColorDisabled: 'rgba(255, 255, 255, 0.01)',
  },
  Button: {
    textColorPrimary: '#ffffff',
    textColorSuccess: '#000000',
    textColorError: '#ffffff',
    borderRadiusMedium: '8px',
    fontWeight: '600',
  },
  Input: {
    color: 'rgba(255, 255, 255, 0.03)',
    colorFocus: 'rgba(255, 255, 255, 0.08)',
    border: '1px solid rgba(255, 255, 255, 0.08)',
    borderFocus: '1px solid #3b82f6',
    borderRadius: '8px',
    textColor: '#ffffff',
    placeholderColor: '#52525b',
    boxShadowFocus: '0 0 0 2px rgba(59, 130, 246, 0.2)',
  },
  Card: {
    color: 'rgba(26, 29, 41, 0.6)',
    borderColor: 'rgba(255, 255, 255, 0.05)',
  },
  Tabs: {
    tabTextColor: '#71717a',
    tabTextColorActive: '#ffffff',
    tabTextColorHover: '#a1a1aa',
    barColor: '#3b82f6',
  },
}
</script>

<template>
  <NConfigProvider :theme="darkTheme" :theme-overrides="themeOverrides">
    <NMessageProvider>
      <NDialogProvider>
        <NGlobalStyle />
        <RouterView />
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>

<style>
/* Global anti-flash and base styles */
html, body, #app {
  background: #0f1117 !important;
  height: 100%;
  margin: 0;
  color: #ffffff;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Eliminate 300ms tap delay on mobile */
a, button, [role="button"], input, select, textarea, label, .n-button {
  touch-action: manipulation;
}

/* Glassmorphism Utilities */
.glass-panel {
  background: rgba(24, 24, 27, 0.4);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.glass-panel-heavy {
  background: rgba(24, 24, 27, 0.8);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.glass-panel-light {
  background: rgba(255, 255, 255, 0.03);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

/* Transitions — kept fast (150ms) to avoid perceived lag */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Custom Scrollbar */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}

/* Gradient Text */
.text-gradient {
  background: linear-gradient(135deg, #ffffff 0%, #a1a1aa 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.text-gradient-primary {
  background: linear-gradient(135deg, #60a5fa 0%, #3b82f6 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}



/* ==================== Card Slide-Up Animation ==================== */
@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.animate-slide-up {
  animation: slideUp 0.35s ease both;
}

/* Button Micro-interactions removed (Phase 10: caused sticky feel on iOS Safari) */
</style>
