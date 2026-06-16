<template>
  <aside
    class="status-sidebar"
    :class="{ open, resizing }"
    :style="open ? { width: sidebarWidth + 'px' } : {}"
  >
    <!-- Drag handle on the left edge -->
    <div class="resize-handle" @mousedown.prevent="startResize" />

    <div class="status-header">
      <div class="tab-bar">
        <button class="tab-btn" :class="{ active: activeTab === 'server' }" @click="activeTab = 'server'">
          Server
          <span v-if="serverJobs.length" class="tab-badge tab-badge--running">{{ serverJobs.length }}</span>
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'session' }" @click="activeTab = 'session'">
          Session
          <span v-if="sessionHistory.length" class="tab-badge">{{ sessionHistory.length }}</span>
        </button>
      </div>
      <button class="close-btn" @click="$emit('close')" aria-label="Close">×</button>
    </div>

    <!-- ── Server Status tab ── -->
    <div v-if="activeTab === 'server'" class="status-body">

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

      <div class="divider" />

      <div class="poll-row">
        <span class="pulse-dot" :class="{ active: serverJobs.length > 0 }" />
        <span class="poll-label">Auto-refresh every 3s</span>
        <button class="refresh-btn" @click="refresh" title="Refresh now">↻</button>
      </div>

    </div>

    <!-- ── Session Jobs tab ── -->
    <div v-else class="status-body status-body--split" style="position:relative">

      <!-- ── Inline confirmation overlay ── -->
      <div v-if="confirming" class="confirm-overlay">
        <div class="confirm-card">
          <p class="confirm-title">{{ confirmConfig.title }}</p>
          <p class="confirm-body">{{ confirmConfig.body }}</p>
          <div class="confirm-footer">
            <button class="btn-cancel" @click="confirming = null">Cancel</button>
            <button
              class="btn-action"
              :class="confirmConfig.danger ? 'btn-action--danger' : 'btn-action--safe'"
              @click="runConfirmed"
            >{{ confirmConfig.label }}</button>
          </div>
        </div>
      </div>

      <div class="section-label">
        Jobs This Session
        <span v-if="sessionHistory.length === 0" class="section-empty"> — none yet</span>
        <button
          v-if="sessionHistory.length > 0"
          class="clear-btn"
          @click="confirmClearHistory"
          title="Clear session job history"
        >Clear</button>
      </div>

      <div class="scroll-section" ref="jobsSectionEl">
        <div
          v-for="h in [...sessionHistory].reverse()"
          :key="h.id"
          class="hist-card"
        >
          <div class="hist-row">
            <span class="hist-dot" :class="`hist-dot--${h.status}`" />
            <span class="hist-name">{{ formatKey(h.key) }}</span>
            <a
              v-if="h.logPath"
              :href="`/${h.logPath}`"
              target="_blank"
              rel="noopener"
              class="run-link"
              title="Open log file"
            >Log ↗</a>
            <button class="view-btn" @click="view(h.id)">View</button>
          </div>
          <div class="hist-meta">
            <span class="hist-time">{{ formatTime(h.startedAt) }}</span>
            <span v-if="h.endedAt" class="hist-dur">{{ formatDur(h.endedAt - h.startedAt) }}</span>
            <span v-else class="hist-dur running-pulse">running</span>
            <span class="hist-lines">{{ h.lines.length }} lines</span>
          </div>
        </div>
      </div>

      <!-- Drag handle doubles as the divider -->
      <div
        class="section-resize-handle"
        :class="{ 'section-resize-handle--active': resizingRuns }"
        @mousedown.prevent="startRunsResize"
        title="Drag to resize"
      />

      <!-- Report Runs — links to on-disk log/data files -->
      <div class="section-label">
        Report Runs
        <button class="refresh-btn" @click="loadRuns" title="Refresh">↻</button>
        <button
          v-if="runs.length > 0"
          class="clear-btn"
          @click="confirmClearRuns"
          title="Delete all run directories from disk"
        >Clear</button>
      </div>

      <div
        class="scroll-section"
        ref="runsSectionEl"
        :style="runsHeight ? { height: runsHeight + 'px', flex: 'none' } : {}"
      >
        <div v-if="runsLoading" class="empty-state">Loading…</div>
        <div v-else-if="runs.length === 0" class="empty-state">No report runs found</div>

        <div v-for="run in runs" :key="run.path" class="run-card">
          <div class="run-row">
            <span class="run-label">{{ formatRunLabel(run) }}</span>
            <div class="run-links">
              <a
                v-if="run.has_log && run.log_name"
                :href="`/reports/${run.date}/${run.time}/${run.log_name}`"
                target="_blank"
                rel="noopener"
                class="run-link"
                title="Open log file"
              >Log ↗</a>
              <a
                v-if="run.has_data"
                :href="`/api/runs/${run.date}/${run.time}/data`"
                target="_blank"
                rel="noopener"
                class="run-link"
                title="Browse data files"
              >Data ↗</a>
            </div>
          </div>
        </div>
      </div><!-- end scroll-section (runs) -->

    </div>

  </aside>
</template>

<script setup>
import { ref, watch } from 'vue'

const MIN_WIDTH = 220
const DEFAULT_WIDTH = 280

const sidebarWidth = ref(DEFAULT_WIDTH)
const resizing = ref(false)

function startResize(e) {
  resizing.value = true
  const startX     = e.clientX
  const startWidth = sidebarWidth.value

  function onMove(ev) {
    const maxWidth = Math.floor(window.innerWidth / 2)
    sidebarWidth.value = Math.max(MIN_WIDTH, Math.min(maxWidth, startWidth + (startX - ev.clientX)))
  }
  function onUp() {
    resizing.value = false
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}
import { useServerStatus } from '../composables/useServerStatus.js'
import { useJobs } from '../composables/useJobs.js'

const props = defineProps({
  open: { type: Boolean, required: true },
})
const emit = defineEmits(['close'])

const activeTab = ref('server')

const { serverJobs, refresh } = useServerStatus(() => props.open)
const { jobs, sessionHistory, cancelJob: _cancelJob, reopenJob, clearHistory } = useJobs()

// ── Report runs ──────────────────────────────────────────────────────────────
const runs = ref([])
const runsLoading = ref(false)

async function loadRuns() {
  runsLoading.value = true
  try {
    const r = await fetch('/api/runs')
    if (r.ok) runs.value = await r.json()
  } catch { /* ignore */ } finally {
    runsLoading.value = false
  }
}

// Load runs when switching to session tab for the first time
watch(activeTab, v => { if (v === 'session' && runs.value.length === 0) loadRuns() })
watch(() => props.open, v => { if (v && activeTab.value === 'session') loadRuns() })

// ── Formatting ────────────────────────────────────────────────────────────────
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

function formatTime(ts) {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

function formatDur(ms) {
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

function formatRunLabel(run) {
  // "20260615/201347" → "2026-06-15  20:13:47"
  const d = run.date   // "20260615"
  const t = run.time   // "201347"
  return `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}  ${t.slice(0,2)}:${t.slice(2,4)}:${t.slice(4,6)}`
}

// ── Actions ───────────────────────────────────────────────────────────────────
function isClientTracked(key) {
  return jobs.value.some(j => j.key === key && j.status === 'running')
}

function stopJob(key) {
  const j = jobs.value.find(j => j.key === key && j.status === 'running')
  if (j) _cancelJob(j.id)
}

function view(id) {
  reopenJob(id)
}

// ── Runs section vertical resize ─────────────────────────────────────────────
const runsSectionEl = ref(null)
const jobsSectionEl = ref(null)
const runsHeight    = ref(null)   // null = flex:1 equal split
const resizingRuns  = ref(false)

function startRunsResize(e) {
  resizingRuns.value = true
  const startY      = e.clientY
  const startHeight = runsSectionEl.value?.getBoundingClientRect().height ?? 200

  function onMove(ev) {
    const delta = startY - ev.clientY   // drag up → positive → taller runs
    runsHeight.value = Math.max(60, startHeight + delta)
  }
  function onUp() {
    resizingRuns.value = false
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

// ── Inline confirmation ───────────────────────────────────────────────────────
const confirming = ref(null)   // null | 'history' | 'runs'
const confirmConfig = ref({})

function confirmClearHistory() {
  const finished = sessionHistory.value.filter(h => h.status !== 'running').length
  const running  = sessionHistory.value.filter(h => h.status === 'running').length
  confirmConfig.value = {
    title:  'Clear Session History?',
    body:   running
      ? `Removes ${finished} finished entr${finished === 1 ? 'y' : 'ies'} from the in-memory log. ${running} running job${running === 1 ? '' : 's'} will not be affected. No files are deleted.`
      : `Removes all ${finished} entr${finished === 1 ? 'y' : 'ies'} from the in-memory session log. No files are deleted.`,
    label:  'Clear History',
    danger: false,
  }
  confirming.value = 'history'
}

function confirmClearRuns() {
  const count = runs.value.length
  confirmConfig.value = {
    title:  'Delete Report Runs?',
    body:   `Permanently deletes all ${count} run director${count === 1 ? 'y' : 'ies'} from disk, including all log files and data snapshots. This cannot be undone.`,
    label:  'Delete from Disk',
    danger: true,
  }
  confirming.value = 'runs'
}

async function runConfirmed() {
  const action = confirming.value
  confirming.value = null
  if (action === 'history') {
    clearHistory()
  } else if (action === 'runs') {
    try {
      const r = await fetch('/api/runs', { method: 'DELETE' })
      if (r.ok) runs.value = []
    } catch (err) {
      console.error('Failed to clear runs:', err)
    }
  }
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
  position: relative;
}
.status-sidebar.open { width: 280px; }  /* fallback — overridden by inline style */
.status-sidebar.resizing { transition: none; }

/* ── Resize handle — left edge ── */
.resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 5px;
  cursor: ew-resize;
  z-index: 10;
  transition: background 0.15s;
}
.resize-handle:hover,
.status-sidebar.resizing .resize-handle {
  background: var(--action, #2563eb);
  opacity: 0.5;
}

/* ── Header + tab bar ── */
.status-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0 0.5rem 0 0.75rem;
  height: 44px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}
.tab-bar {
  display: flex;
  gap: 2px;
  flex: 1;
}
.tab-btn {
  flex: 1;
  background: none;
  border: none;
  border-radius: 4px;
  color: var(--text-3);
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 500;
  letter-spacing: 0.03em;
  padding: 4px 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  transition: color 0.15s, background 0.15s;
}
.tab-btn:hover { color: var(--text-1); background: var(--surface-alt); }
.tab-btn.active { color: var(--text-1); background: var(--surface-alt); font-weight: 600; }

.tab-badge {
  font-size: 0.68rem;
  font-weight: 700;
  background: var(--border);
  color: var(--text-2);
  border-radius: 8px;
  padding: 0 5px;
  line-height: 1.5;
}
.tab-badge--running {
  background: rgba(63, 185, 80, 0.25);
  color: #3fb950;
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  font-size: 1.1rem;
  line-height: 1;
  padding: 0 2px;
  flex-shrink: 0;
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
  min-height: 0;
}

/* Session tab: two independently-scrollable halves */
.status-body--split {
  overflow: hidden;
}
.scroll-section {
  flex: 1;
  min-height: 60px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.section-label {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-3);
  margin-bottom: 0.1rem;
}
.section-empty {
  font-weight: 400;
  text-transform: none;
  letter-spacing: 0;
  font-style: italic;
  color: var(--text-3);
  font-size: 0.72rem;
}

.empty-state {
  font-size: 0.82rem;
  color: var(--text-3);
  font-style: italic;
  padding: 0.25rem 0;
}

/* ── Server status: running job card ── */
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
.job-key { font-size: 0.72rem; color: var(--text-3); background: none; }
.job-elapsed { font-size: 0.75rem; color: var(--text-2); font-family: monospace; white-space: nowrap; }
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
.orphan-hint { font-size: 0.72rem; color: var(--text-3); font-style: italic; }

/* ── Session history card ── */
.hist-card {
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.45rem 0.65rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.hist-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.hist-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.hist-dot--running  { background: var(--action); animation: pulse 1.5s ease-in-out infinite; }
.hist-dot--done     { background: #3fb950; }
.hist-dot--error    { background: #f85149; }
.hist-dot--cancelled{ background: var(--text-3); }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.35; }
}

.hist-name {
  font-size: 0.83rem;
  font-weight: 500;
  color: var(--text-1);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.view-btn {
  font-size: 0.72rem;
  padding: 2px 9px;
  background: none;
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--text-2);
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}
.view-btn:hover { border-color: var(--action); color: var(--action); }

.hist-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.72rem;
  color: var(--text-3);
  font-family: monospace;
}
.hist-time  { color: var(--text-3); }
.hist-dur   { color: var(--text-2); }
.hist-lines { margin-left: auto; }
.running-pulse { color: #3fb950; animation: pulse 1.5s ease-in-out infinite; }

/* ── Report runs card ── */
.run-card {
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.4rem 0.65rem;
}
.run-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.run-label {
  font-size: 0.78rem;
  font-family: monospace;
  color: var(--text-2);
  flex: 1;
}
.run-links { display: flex; gap: 0.4rem; flex-shrink: 0; }
.run-link {
  font-size: 0.72rem;
  color: var(--badge-ro-text);
  text-decoration: none;
  padding: 1px 6px;
  border: 1px solid var(--badge-ro-text);
  border-radius: 3px;
  opacity: 0.85;
  white-space: nowrap;
}
.run-link:hover { opacity: 1; background: var(--badge-ro-bg); }

/* ── Section resize handle (between Jobs and Runs) ── */
.section-resize-handle {
  flex-shrink: 0;
  height: 5px;
  margin: 0.15rem 0;
  cursor: ns-resize;
  position: relative;
  transition: background 0.15s;
}
.section-resize-handle::after {
  content: '';
  position: absolute;
  inset: 2px 0;
  border-top: 1px solid var(--border);
  transition: border-color 0.15s;
}
.section-resize-handle:hover::after,
.section-resize-handle--active::after {
  border-color: var(--action);
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
.pulse-dot.active { background: #3fb950; animation: pulse 2s ease-in-out infinite; }
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

.clear-btn {
  margin-left: auto;
  background: none;
  border: 1px solid transparent;
  border-radius: 3px;
  color: var(--text-3);
  cursor: pointer;
  font-size: 0.67rem;
  font-weight: 500;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  padding: 1px 6px;
  line-height: 1.5;
  transition: color 0.15s, border-color 0.15s;
}
.clear-btn:hover {
  color: #f85149;
  border-color: #f85149;
}

/* ── Inline confirmation overlay ── */
.confirm-overlay {
  position: absolute;
  inset: 0;
  background: var(--surface);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  z-index: 20;
}
.confirm-card {
  width: 100%;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.1rem 1rem 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.confirm-title {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-1);
}
.confirm-body {
  margin: 0;
  font-size: 0.8rem;
  color: var(--text-2);
  line-height: 1.5;
}
.confirm-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding-top: 0.25rem;
}
.btn-cancel {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-2);
  padding: 5px 14px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.82rem;
  transition: border-color 0.15s, color 0.15s;
}
.btn-cancel:hover { border-color: var(--text-2); color: var(--text-1); }
.btn-action {
  border: none;
  color: #fff;
  padding: 5px 14px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 500;
  transition: background 0.15s;
}
.btn-action--safe   { background: #16a34a; }
.btn-action--safe:hover  { background: #15803d; }
.btn-action--danger { background: #dc2626; }
.btn-action--danger:hover { background: #b91c1c; }
</style>
