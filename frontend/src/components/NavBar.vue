<template>
  <header class="nav-bar">
    <div class="brand">
      <span class="brand-tag">PMW 120</span>
      <span class="brand-divider">|</span>
      <span class="brand-name">NCE Safe Simulator</span>
    </div>
    <div class="nav-actions">
      <button class="status-btn" :class="{ active: runningCount > 0 }" @click="$emit('toggle-status')">
        <span v-if="runningCount > 0" class="status-dot" />
        {{ runningCount > 0 ? `${runningCount} running` : 'Status' }}
      </button>
      <button class="theme-btn" @click="toggle">
        {{ theme === 'dark' ? '☀ Light' : '☾ Dark' }}
      </button>
    </div>
  </header>
</template>

<script setup>
import { useTheme } from '../composables/useTheme.js'
const { theme, toggle } = useTheme()
defineProps({ runningCount: { type: Number, default: 0 } })
defineEmits(['toggle-status'])
</script>

<style scoped>
/* Nav is always dark regardless of page theme. */
.nav-bar {
  height: 48px;
  flex-shrink: 0;
  background: #161b22;
  border-bottom: 2px solid var(--accent);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 1.25rem;
  gap: 1rem;
}
.nav-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}
.brand-tag {
  color: var(--accent);
  font-weight: 700;
  font-size: 0.8rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.brand-divider { color: #6e7681; }
.brand-name {
  color: #e6edf3;
  font-weight: 500;
  font-size: 0.95rem;
}

.theme-btn {
  background: transparent;
  border: 1px solid #30363d;
  color: #e6edf3;
  padding: 4px 10px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.8rem;
  white-space: nowrap;
  transition: background 0.15s;
}
.theme-btn:hover { background: #30363d; }

.status-btn {
  background: transparent;
  border: 1px solid #30363d;
  color: #8b949e;
  padding: 4px 10px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.8rem;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.status-btn:hover { background: #30363d; color: #e6edf3; }
.status-btn.active { border-color: #3fb950; color: #3fb950; }
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #3fb950;
  animation: pulse 2s ease-in-out infinite;
  flex-shrink: 0;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}
</style>
