<template>
  <aside class="status-sidebar" :class="{ open }">
    <div class="status-header">
      <span class="status-title">Server Status</span>
      <button class="close-btn" @click="$emit('close')" aria-label="Close">×</button>
    </div>

    <div class="status-body">

      <!-- Running jobs -->
      <div class="section-label">Running Jobs</div>

      <div v-if="serverJobs.length === 0" class="empty-state">
        No jobs running
      </div>

      <div
        v-for="job in serverJobs"
        :key="job.key"
        class="job-card"
      >
        <div class="job-row">
          <span class="job-spinner" />
          <span class="job-name">{{ formatKey(job.key) }}</span>
        </div>
        <div class="job-meta">
          <code class="job-key">{{ job.key }}</code>
          <span class="job-elapsed">{{ formatElapsed(job.elapsed_seconds) }}</span>
        </div>
        <div class="job-actions">
          <button
            v-if="isClientTracked(job.key)"
            class="stop-btn"
            @click="stopJob(job.key)"
          >Stop</button>
          <span v-else class="orphan-hint">started before this session</span>
        </div>
      </div>

      <!-- Divider -->
      <div class="divider" />

      <!-- Poll indicator -->
      <div class="poll-row">
        <span class="pulse-dot" :class="{ active: serverJobs.length > 0 }" />
        <span class="poll-label">Auto-refresh every 3s</span>
        <button class="refresh-btn" @click="refresh" title="Refresh now">↻</button>
      </div>

    </div>
  </aside>
</template>

<script setup>
import { useServerStatus } from '../composables/useServerStatus.js'
import { useJobs } from '../composables/useJobs.js'

const props = defineProps({
  open: { type: Boolean, required: true },
})
defineEmits(['close'])

const { serverJobs, refresh } = useServerStatus(() => props.open)
const { jobs, cancelJob } = useJobs()

const ACRONYMS = new Set(['roam', 'wsjf', 'bv', 'piid', 'pi'])
function formatKey(key) {
  return key.split('-').map(w =>
    ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)
  ).join(' ')
}

function formatElapsed(s) {
  if (s < 60) return `${Math.floor(s)}s`
  const m = Math.floor(s / 60)
  return `${m}m ${Math.floor(s % 60)}s`
}

function isClientTracked(key) {
  return jobs.value.some(j => j.key === key && j.status === 'running')
}

function stopJob(key) {
  const j = jobs.value.find(j => j.key === key && j.status === 'running')
  if (j) cancelJob(j.id)
}
</script>

<style scoped>
.status-sidebar {
  width: 0;
  flex-shrink: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-left: 1px solid var(--border);
  transition: width 0.2s ease;
}
.status-sidebar.open { width: 260px; }

/* ── Header ── */
.status-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 0.85rem;
  height: 44px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}
.status-title {
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-2);
}
.close-btn {
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  font-size: 1.1rem;
  line-height: 1;
  padding: 0 2px;
}
.close-btn:hover { color: var(--text-1); }

/* ── Body ── */
.status-body {
  flex: 1;
  overflow-y: auto;
  padding: 0.65rem 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  min-width: 260px;
}

.section-label {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-3);
  margin-bottom: 0.1rem;
}

/* ── Empty state ── */
.empty-state {
  font-size: 0.82rem;
  color: var(--text-3);
  font-style: italic;
  padding: 0.25rem 0;
}

/* ── Job card ── */
.job-card {
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.55rem 0.7rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.job-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.job-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid var(--border);
  border-top-color: var(--action);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }
.job-name {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.job-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.job-key {
  font-size: 0.72rem;
  color: var(--text-3);
  background: none;
}
.job-elapsed {
  font-size: 0.75rem;
  color: var(--text-2);
  font-family: monospace;
  white-space: nowrap;
}
.job-actions { display: flex; align-items: center; gap: 0.5rem; }
.stop-btn {
  font-size: 0.75rem;
  padding: 2px 10px;
  background: none;
  border: 1px solid #f85149;
  border-radius: 3px;
  color: #f85149;
  cursor: pointer;
}
.stop-btn:hover { background: rgba(248, 81, 73, 0.12); }
.orphan-hint {
  font-size: 0.72rem;
  color: var(--text-3);
  font-style: italic;
}

/* ── Footer ── */
.divider { border-top: 1px solid var(--border); margin: 0.25rem 0; }
.poll-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.75rem;
  color: var(--text-3);
}
.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--border);
  flex-shrink: 0;
}
.pulse-dot.active {
  background: #3fb950;
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}
.poll-label { flex: 1; }
.refresh-btn {
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  font-size: 1rem;
  padding: 0 2px;
  line-height: 1;
}
.refresh-btn:hover { color: var(--text-1); }
</style>
