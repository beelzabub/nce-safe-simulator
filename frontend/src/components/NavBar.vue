<template>
  <header class="nav-bar">
    <!-- Carrier silhouette — fixed-position background, lines up with main pane -->
    <div class="nav-hero" :style="{ backgroundImage: `url(${heroSrc})` }" aria-hidden="true" />

    <div class="brand">
      <button class="jobs-btn" @click="$emit('toggle-jobs')" aria-label="Toggle job list">☰</button>
      <img class="brand-logo" :src="logoSrc" alt="NCE — Navintel Cloud Ecosystem" />
      <span class="brand-tag">PMW 120</span>
      <span class="brand-divider">|</span>
      <span class="brand-name">Safe Simulator</span>
    </div>
    <!-- Wrapper div: ClockWidget is multi-root (widget + Teleport), so a class
         set on the component itself would be dropped as a fallthrough attr -->
    <div class="nav-clock"><ClockWidget /></div>
    <div class="nav-actions">
      <button class="status-btn" :class="{ active: runningCount > 0 }" @click="$emit('toggle-status')">
        <span v-if="runningCount > 0" class="status-dot" />
        {{ runningCount > 0 ? `${runningCount} running` : 'Status' }}
      </button>
      <button class="config-btn" @click="$emit('toggle-config')" title="Edit config.json">⚙</button>
      <button class="help-btn" @click="$emit('toggle-help')">?<span class="btn-label"> Help</span></button>
      <button class="theme-btn" @click="toggle">
        {{ theme === 'dark' ? '☀' : '☾' }}<span class="btn-label">{{ theme === 'dark' ? ' Light' : ' Dark' }}</span>
      </button>
      <button class="signout-btn" title="Sign out" @click="signOut">⎋<span class="btn-label"> Sign out</span></button>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useTheme } from '../composables/useTheme.js'
import { useAuthGate } from '../composables/useAuthGate.js'
import heroSrc from '../assets/hero-carrier.png'
import logoWhite from '../assets/nce-logo-white.png'  // white emblem — for dark UI
import logoNavy from '../assets/nce-logo-navy.png'    // navy emblem — for light UI
import ClockWidget from './ClockWidget.vue'

const { theme, toggle } = useTheme()
const logoSrc = computed(() => (theme.value === 'dark' ? logoWhite : logoNavy))
defineProps({ runningCount: { type: Number, default: 0 } })
defineEmits(['toggle-jobs', 'toggle-status', 'toggle-config', 'toggle-help'])

const router = useRouter()

// Re-locks the front door without closing the browser (issue #157). DoD
// banner acknowledgment survives — consent is per browser session,
// authentication is not.
async function signOut() {
  await useAuthGate().logout()
  router.push('/login')
}
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
  overflow: visible;
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
.brand-logo {
  height: 34px;
  width: auto;
  display: block;
  flex-shrink: 0;
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

.help-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-2);
  padding: 4px 10px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.8rem;
  white-space: nowrap;
  transition: background 0.15s, color 0.15s;
}
.help-btn:hover { background: var(--border); color: var(--text-1); }

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

.signout-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-2);
  padding: 4px 10px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.8rem;
  white-space: nowrap;
}

.signout-btn:hover { background: var(--border); color: var(--text-1); }

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

/* ── Jobs drawer toggle — mobile only ── */
.jobs-btn {
  display: none;
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-1);
  border-radius: 5px;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
  padding: 4px 8px;
}

/* ── Mobile (issue #160) ── */
@media (max-width: 768px) {
  .nav-bar { padding: 0 0.6rem; gap: 0.5rem; }

  /* background-attachment: fixed is unsupported/janky on iOS Safari */
  .nav-hero { background-attachment: scroll; }

  .jobs-btn { display: block; }
  .nav-clock, .brand-tag, .brand-divider, .brand-name { display: none; }
  .btn-label { display: none; }
  .help-btn, .theme-btn, .signout-btn { padding: 4px 8px; }
}

/* Narrowest phones (320px): shave the leftovers so the bar can't overflow.
   The logo goes too — with Sign out (#157) in the bar, six 40px touch targets
   are all a 320px row can hold. */
@media (max-width: 380px) {
  .nav-bar { padding: 0 0.35rem; gap: 0.25rem; }
  .brand { gap: 0.35rem; }
  .brand-logo { display: none; }
  .nav-actions { gap: 0.25rem; }
  .status-btn { font-size: 0.72rem; padding: 4px 6px; }
}

/* Comfortable tap targets without disturbing the 52px bar */
@media (pointer: coarse) {
  .jobs-btn, .status-btn, .config-btn, .help-btn, .theme-btn, .signout-btn {
    min-height: 40px;
    min-width: 40px;
    justify-content: center;
  }
}
</style>
