<template>
  <div class="runner">

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
        <div class="tab-header" @click="toggleCollapse(job.id)">
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
        </div>

        <!-- Log pane -->
        <div v-if="!job.collapsed" class="tab-body">
          <LogPane :lines="job.lines" />
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import LogPane from '../components/LogPane.vue'
import { useJobs } from '../composables/useJobs.js'

const { jobs, cancelJob, closeJob, toggleCollapse } = useJobs()

const ACRONYMS = new Set(['roam', 'wsjf', 'bv', 'piid', 'pi'])
function formatKey(key) {
  return key.split('-').map(w =>
    ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)
  ).join(' ')
}
</script>

<style scoped>
.runner {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* ── Placeholder ── */
.placeholder {
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

/* ── Tab header ── */
.tab-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.45rem 0.75rem;
  background: var(--surface, #161b22);
  cursor: pointer;
  user-select: none;
  flex-shrink: 0;
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

/* ── Log body ── */
.tab-body {
  height: 300px;
  overflow: hidden;
}
.tab--running .tab-body {
  flex: 1;
  height: auto;
  min-height: 0;
}
</style>
