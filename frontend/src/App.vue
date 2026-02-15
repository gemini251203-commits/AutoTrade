<script setup lang="ts">
import { onMounted } from 'vue'
import { NConfigProvider, NMessageProvider, NDialogProvider, darkTheme, NGlobalStyle } from 'naive-ui'
import { RouterView } from 'vue-router'
import { useAuthStore } from './stores/auth'

// 🔥 Initialize auth on app startup to restore session from localStorage
const authStore = useAuthStore()
onMounted(() => {
  authStore.initialize()
})

// Custom theme overrides for cyberpunk style
const themeOverrides = {
  common: {
    primaryColor: '#8a2be2',
    primaryColorHover: '#9d4ede',
    primaryColorPressed: '#7025c2',
    primaryColorSuppl: '#8a2be2',
    successColor: '#00c853',
    successColorHover: '#00e676',
    errorColor: '#ff4757',
    errorColorHover: '#ff6b7a',
    borderRadius: '8px',
    borderColor: 'rgba(255, 255, 255, 0.1)',
    inputColor: '#0f0f18',
    inputColorDisabled: '#1a1a25',
    tableColor: '#111',
    cardColor: '#111',
    modalColor: '#0f0f18',
    bodyColor: '#0a0a0a',
    popoverColor: '#111',
    textColor1: '#ffffff',
    textColor2: '#9ca3af',
    textColor3: '#6b7280',
  },
  Button: {
    textColorPrimary: '#ffffff',
    textColorSuccess: '#ffffff',
    textColorError: '#ffffff',
  },
  Input: {
    color: '#0f0f18',
    colorFocus: '#0f0f18',
    border: '1px solid rgba(255,255,255,0.1)',
    borderFocus: '1px solid #8a2be2',
    textColor: '#ffffff',
    placeholderColor: '#4b5563',
  },
  Tabs: {
    tabTextColor: '#6b7280',
    tabTextColorActive: '#ffffff',
    tabTextColorHover: '#9ca3af',
    barColor: '#8a2be2',
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
/* Global anti-flash styles */
html, body, #app {
  background: #0a0a0a !important;
}
</style>
