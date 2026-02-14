/**
 * Main Entry Point
 * =================
 * Vue 3 app initialization with Pinia, Router, and global styles.
 */

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import './style.css'

// Import Naive UI fonts
import 'vfonts/Lato.css'
import 'vfonts/FiraCode.css'

// Create Vue app
const app = createApp(App)

// Install plugins
app.use(createPinia())
app.use(router)

// Mount app
app.mount('#app')
