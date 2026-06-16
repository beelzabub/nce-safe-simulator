<template>
  <header class="nav-bar">
    <!-- Carrier silhouette — fixed-position background, lines up with main pane -->
    <div class="nav-hero" :style="{ backgroundImage: `url(${heroSrc})` }" aria-hidden="true" />

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
      <button class="config-btn" @click="$emit('toggle-config')" title="Edit config.json">⚙</button>
      <button class="theme-btn" @click="toggle">
        {{ theme === 'dark' ? '☀ Light' : '☾ Dark' }}
      </button>
    </div>
  </header>
</template>

<script setup>
import { useTheme } from '../composables/useTheme.js'
import heroSrc from '../assets/hero-carrier.png'

const { theme, toggle } = useTheme()
defineProps({ runningCount: { type: Number, default: 0 } })
defineEmits(['toggle-status', 'toggle-config'])
</script>

<style scoped>
.nav-bar {
  position: relative;
  height: 52px;
  flex-shrink: 0;
  background: var(--bg);
  border-bottom: 2px solid rgba(252, 109, 38, 0.25);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 1.25rem;
  gap: 1rem;
  overflow: hidden;
}

/* ── Hero background — fixed to viewport so it lines up with main pane ── */
.nav-hero {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: 65% 30%;
  background-attachment: fixed;
  background-repeat: no-repeat;
  opacity: 0.12;
  pointer-events: none;
  z-index: 0;
  -webkit-mask-image: linear-gradient(to right, transparent 0%, black 18%, black 82%, transparent 100%);
  mask-image:         linear-gradient(to right, transparent 0%, black 18%, black 82%, transparent 100%);
}

/* ── Brand + actions float above the image ── */
.brand, .nav-actions {
  position: relative;
  z-index: 1;
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
.brand-divider { color: var(--text-3); }
.brand-name {
  color: var(--text-1);
  font-weight: 500;
  font-size: 0.95rem;
}

.config-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-2);
  width: 30px;
  height: 30px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
  transition: background 0.15s, color 0.15s;
}
.config-btn:hover { background: var(--border); color: var(--text-1); }

.theme-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-1);
  padding: 4px 10px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.8rem;
  white-space: nowrap;
  transition: background 0.15s;
}
.theme-btn:hover { background: var(--border); }

.status-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-2);
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
.status-btn:hover { background: var(--border); color: var(--text-1); }
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
