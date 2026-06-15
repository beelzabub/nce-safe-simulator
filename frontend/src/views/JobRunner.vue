<template>
  <div class="runner">

    <!-- Carrier silhouette — fixed to viewport, lines up with NavBar -->
    <div class="runner-hero" :style="{ backgroundImage: `url(${heroSrc})` }" aria-hidden="true" />

    <div v-if="jobs.length === 0" class="placeholder">
      <span class="placeholder-icon">⚙</span>
      <p>Select a job and click Launch to run it.</p>
    </div>

    <div v-else class="tabs-container">
      <div
        v-for="job in jobs"
        :key="job.id"
        class="tab"
        :class="`tab--${job.status}`"
      >
        <!-- Header row — click to collapse/expand -->
        <div
          class="tab-header"
          @click="toggleCollapse(job.id)"
          @mouseenter="!job._closePinned && pauseClose(job.id)"
          @mouseleave="!job._closePinned && resumeClose(job.id)"
        >
          <span class="tab-status">
            <span v-if="job.status === 'running'"    class="spinner" />
            <span v-else-if="job.status === 'done'"      class="badge badge--done">✓</span>
            <span v-else-if="job.status === 'cancelled'" class="badge badge--cancelled">◼</span>
            <span v-else                                  class="badge badge--error">✕</span>
          </span>
          <span class="tab-label">{{ formatKey(job.key) }}</span>
          <span v-if="job.collapsed" class="tab-summary">{{ job.lines.length }} lines</span>
          <span class="tab-spacer" />
          <button
            v-if="job.status === 'running'"
            class="tab-stop"
            @click.stop="cancelJob(job.id)"
            aria-label="Stop job"
          >Stop</button>
          <button
            v-else
            class="tab-close"
            @click.stop="closeJob(job.id)"
            aria-label="Close tab"
          >×</button>

          <!-- Countdown bar: drains left→right over closeDuration; click to pin/unpin -->
          <div
            v-if="job.closeDuration > 0"
            class="countdown-bar"
            :class="{ 'countdown-bar--pinned': job._closePinned }"
            :style="`--dur: ${job.closeDuration / 1000}s`"
            :title="job._closePinned ? 'Click to restart countdown' : 'Click to freeze countdown'"
            @click.stop="toggleClosePin(job.id)"
          />
        </div>

        <!-- Log pane -->
        <div v-if="!job.collapsed" class="tab-body" :class="{ 'tab-body--resizable': job.status !== 'running' }">
          <LogPane :lines="job.lines" />
          <div v-if="job.status !== 'running'" class="resize-handle" @mousedown.prevent.stop="startResize" title="Drag to resize" />
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import LogPane from '../components/LogPane.vue'
import { useJobs } from '../composables/useJobs.js'
import heroSrc from '../assets/hero-carrier.png'

const { jobs, cancelJob, closeJob, toggleCollapse, pauseClose, resumeClose, toggleClosePin } = useJobs()

function startResize(e) {
  const body = e.currentTarget.parentElement
  const startY = e.clientY
  const startH = body.getBoundingClientRect().height
  function onMove(ev) {
    const h = Math.max(80, Math.min(window.innerHeight * 0.8, startH + ev.clientY - startY))
    body.style.height = h + 'px'
  }
  function onUp() {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

const ACRONYMS = new Set(['roam', 'wsjf', 'bv', 'piid', 'pi'])
function formatKey(key) {
  return key.split('-').map(w =>
    ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)
  ).join(' ')
}
</script>

<style scoped>
.runner {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* ── Carrier background — same fixed position as NavBar so images align ── */
.runner-hero {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: 65% 30%;
  background-attachment: fixed;
  background-repeat: no-repeat;
  opacity: 0.12;
  pointer-events: none;
  z-index: 0;
  -webkit-mask-image: radial-gradient(ellipse 80% 70% at 60% 45%, black 20%, transparent 75%);
  mask-image:         radial-gradient(ellipse 80% 70% at 60% 45%, black 20%, transparent 75%);
}

/* ── Placeholder ── */
.placeholder {
  position: relative;
  z-index: 1;
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-2, #8b949e);
}
.placeholder-icon { font-size: 2rem; margin-bottom: 0.5rem; opacity: 0.4; }
.placeholder p { margin: 0.2rem 0; font-size: 0.9rem; }

/* ── Tab container ── */
.tabs-container {
  position: relative;
  z-index: 1;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  min-height: 0;
}

/* ── Tab ── */
.tab {
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid var(--border, #30363d);
  min-height: 0;
}
.tab--running { flex: 1; }

/* Subtle red tint on the header row for error tabs */
.tab--error > .tab-header {
  background: rgba(248, 81, 73, 0.08);
}

/* ── Tab header ── */
.tab-header {
  position: relative;       /* anchor for countdown-bar */
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.45rem 0.75rem;
  background: var(--surface, #161b22);
  cursor: pointer;
  user-select: none;
  flex-shrink: 0;
  overflow: hidden;         /* clip the countdown bar */
}
.tab-header:hover { filter: brightness(1.15); }

/* ── Status indicators ── */
.tab-status { display: flex; align-items: center; width: 16px; }

.spinner {
  width: 13px;
  height: 13px;
  border: 2px solid var(--border, #30363d);
  border-top-color: var(--action, #2563eb);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  display: inline-block;
}
@keyframes spin { to { transform: rotate(360deg); } }

.badge { font-size: 0.8rem; font-weight: 700; }
.badge--done      { color: #3fb950; }
.badge--error     { color: #f85149; }
.badge--cancelled { color: #6e7681; }

.tab-label   { font-size: 0.85rem; font-weight: 500; color: var(--text-1, #e6edf3); }
.tab-summary { font-size: 0.75rem; color: var(--text-3, #6e7681); }
.tab-hint    { font-size: 0.72rem; color: var(--text-3, #6e7681); }
.tab-spacer  { flex: 1; }

.tab-stop {
  background: none;
  border: 1px solid #f85149;
  border-radius: 3px;
  color: #f85149;
  cursor: pointer;
  font-size: 0.72rem;
  padding: 1px 6px;
  line-height: 1.4;
}
.tab-stop:hover { background: rgba(248, 81, 73, 0.15); }
.tab-close {
  background: none;
  border: none;
  color: var(--text-3, #6e7681);
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
  padding: 0 2px;
}
.tab-close:hover { color: var(--text-1, #e6edf3); }

/* ── Countdown bar ── */
.countdown-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 5px;
  background: var(--action, #2563eb);
  transform-origin: left center;
  animation: drain var(--dur) linear forwards;
  cursor: pointer;
}
.countdown-bar--pinned {
  background: var(--text-3, #6e7681);
  animation-play-state: paused;
}
.tab-header:hover .countdown-bar:not(.countdown-bar--pinned) {
  animation-play-state: paused;
}
@keyframes drain {
  from { transform: scaleX(1); }
  to   { transform: scaleX(0); }
}

/* ── Log body ── */
.tab-body {
  height: 300px;
  overflow: hidden;
}
.tab-body--resizable {
  position: relative;
  min-height: 80px;
  max-height: 80vh;
  overflow: hidden;
}
/* Full-width bottom bar — visual resize indicator */
.tab-body--resizable::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: var(--border);
  transition: background 0.15s;
  pointer-events: none;
}
.tab-body--resizable:hover::after {
  background: var(--accent);
}
/* Custom resize grip — bottom-right corner, easy to grab */
.resize-handle {
  position: absolute;
  bottom: 0;
  right: 0;
  width: 28px;
  height: 28px;
  cursor: ns-resize;
  z-index: 2;
  opacity: 0.35;
  transition: opacity 0.15s;
  background-image:
    radial-gradient(circle, var(--text-1, #e6edf3) 1.5px, transparent 1.5px);
  background-size: 6px 6px;
  background-position: 4px 4px;
  background-repeat: repeat;
}
.resize-handle:hover,
.tab-body--resizable:active .resize-handle {
  opacity: 0.9;
}
.tab--running .tab-body {
  flex: 1;
  height: auto;
  min-height: 0;
}
</style>
