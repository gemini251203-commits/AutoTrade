<template>
  <div class="skeleton-wrapper" :style="wrapperStyle">
    <div v-if="variant === 'card'" class="skeleton-card">
      <div class="skeleton-line skeleton-title" />
      <div class="skeleton-line skeleton-subtitle" />
      <div class="skeleton-line skeleton-body" v-for="i in lines" :key="i" :style="{ width: lineWidth(i) }" />
    </div>
    <div v-else-if="variant === 'chart'" class="skeleton-chart">
      <div class="skeleton-chart-area" />
      <div class="skeleton-chart-labels">
        <div class="skeleton-line skeleton-label" v-for="i in 5" :key="i" />
      </div>
    </div>
    <div v-else-if="variant === 'table'" class="skeleton-table">
      <div class="skeleton-table-row" v-for="i in rows" :key="i">
        <div class="skeleton-line skeleton-cell" v-for="j in cols" :key="j" />
      </div>
    </div>
    <div v-else class="skeleton-line" :style="{ width: width, height: height }" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  variant?: 'card' | 'chart' | 'table' | 'line'
  lines?: number
  rows?: number
  cols?: number
  width?: string
  height?: string
  repeat?: number
}>(), {
  variant: 'card',
  lines: 3,
  rows: 5,
  cols: 4,
  width: '100%',
  height: '20px',
  repeat: 1,
})

const wrapperStyle = computed(() => ({
  '--repeat': props.repeat,
}))

function lineWidth(index: number): string {
  // 不同行不同宽度，看起来更自然
  const widths = ['100%', '85%', '70%', '90%', '60%']
  return widths[(index - 1) % widths.length]
}
</script>

<style scoped>
@keyframes shimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
}

.skeleton-line {
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.06) 25%,
    rgba(255, 255, 255, 0.12) 50%,
    rgba(255, 255, 255, 0.06) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
  border-radius: 6px;
}

.skeleton-card {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-title {
  height: 24px;
  width: 40%;
}

.skeleton-subtitle {
  height: 16px;
  width: 25%;
  opacity: 0.6;
}

.skeleton-body {
  height: 14px;
}

/* Chart Skeleton */
.skeleton-chart {
  padding: 16px;
}

.skeleton-chart-area {
  height: 200px;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.04) 25%,
    rgba(255, 255, 255, 0.08) 50%,
    rgba(255, 255, 255, 0.04) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
  border-radius: 8px;
  margin-bottom: 12px;
}

.skeleton-chart-labels {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.skeleton-label {
  height: 12px;
  width: 40px;
  opacity: 0.5;
}

/* Table Skeleton */
.skeleton-table {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
}

.skeleton-table-row {
  display: flex;
  gap: 12px;
}

.skeleton-cell {
  height: 16px;
  flex: 1;
}

.skeleton-table-row:first-child .skeleton-cell {
  height: 20px;
  opacity: 0.9;
}
</style>
