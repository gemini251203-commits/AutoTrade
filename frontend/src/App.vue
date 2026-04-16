<script setup lang="ts">
import { onMounted } from 'vue'
import { NConfigProvider, NMessageProvider, NDialogProvider, darkTheme, NGlobalStyle } from 'naive-ui'
import { RouterView } from 'vue-router'
import { useAuthStore } from './stores/auth'

// Initialize auth on app startup to restore session from localStorage
const authStore = useAuthStore()
onMounted(() => {
  authStore.initialize()
})

// Custom theme overrides for cyberpunk style
const themeOverrides = {
  common: {
    primaryColor: '#8a2be2', // Electric Purple
    primaryColorHover: '#a855f7',
    primaryColorPressed: '#7025c2',
    primaryColorSuppl: '#8a2be2',
    successColor: '#00e676', // Neo Green
    successColorHover: '#69f0ae',
    warningColor: '#ffeb3b',
    errorColor: '#ff1744', // Neo Red
    errorColorHover: '#ff5252',
    textColor1: '#ffffff',
    textColor2: '#a1a1aa', // Zinc 400
    textColor3: '#52525b', // Zinc 600
    bodyColor: '#000000', // Pitch Black
    cardColor: '#18181b', // Zinc 900
    modalColor: '#18181b',
    popoverColor: '#18181b',
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
    borderFocus: '1px solid #8a2be2',
    borderRadius: '8px',
    textColor: '#ffffff',
    placeholderColor: '#52525b',
    boxShadowFocus: '0 0 0 2px rgba(138, 43, 226, 0.2)',
  },
  Card: {
    color: 'rgba(24, 24, 27, 0.6)',
    borderColor: 'rgba(255, 255, 255, 0.05)',
  },
  Tabs: {
    tabTextColor: '#71717a',
    tabTextColorActive: '#ffffff',
    tabTextColorHover: '#a1a1aa',
    barColor: '#8a2be2',
  },
}
</script>

<template>
  <NConfigProvider :theme="darkTheme" :theme-overrides="themeOverrides">
    <NMessageProvider>
      <NDialogProvider>
        <NGlobalStyle />
        <RouterView v-slot="{ Component }">
          <Transition name="page" mode="out-in" appear>
            <component :is="Component" />
          </Transition>
        </RouterView>
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>

<style>
/* Global anti-flash and base styles */
html, body, #app {
  background: #000000 !important;
  height: 100%;
  margin: 0;
  color: #ffffff;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
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

/* Transitions */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
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
  background: linear-gradient(135deg, #ae69ff 0%, #8a2be2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

/* ==================== Route Transitions ==================== */
.page-enter-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.page-leave-active {
  transition: opacity 0.12s ease;
}
.page-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.page-leave-to {
  opacity: 0;
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

/* ==================== Button Micro-interactions ==================== */
button:not(:disabled):active {
  transform: scale(0.97);
}
</style>
