import { ref, computed } from 'vue'
import { runJob } from '../ws.js'

// Module-level state — singleton shared across all component instances.
const jobs = ref([])
const _sessionHistory = ref([])   // permanent; never cleared; lines shared with jobs entry
const _scrollToId = ref(null)     // JobRunner watches this to scroll-to and clear
let _nextId = 1
let _diskHistoryLoaded = false

// Auto-close delays by terminal status.  Errors stay open until manually
// dismissed — failures need eyes on them.
const AUTOCLOSE_MS = { done: 60_000, cancelled: 30_000 }

function _closeJob(id) {
  const j = jobs.value.find(e => e.id === id)
  if (j?._closeTimer) clearTimeout(j._closeTimer)
  // Mark history entry as closed (preserve endedAt if already set)
  const h = _sessionHistory.value.find(e => e.id === id)
  if (h && !h.endedAt) h.endedAt = Date.now()
  jobs.value = jobs.value.filter(e => e.id !== id)
}

function _scheduleClose(id, ms) {
  const j = jobs.value.find(e => e.id === id)
  if (!j) return
  j.closeDuration = ms
  j.closeAt = Date.now() + ms
  j._closeTimer = setTimeout(() => _closeJob(id), ms)
}

function pauseClose(id) {
  const j = jobs.value.find(e => e.id === id)
  if (!j || !j._closeTimer) return
  clearTimeout(j._closeTimer)
  j._closeTimer = null
  j._closeRemaining = Math.max(0, j.closeAt - Date.now())
}

function resumeClose(id) {
  const j = jobs.value.find(e => e.id === id)
  if (!j || j._closeTimer || !j._closeRemaining) return
  const remaining = j._closeRemaining
  j._closeRemaining = 0
  j.closeAt = Date.now() + remaining
  j._closeTimer = setTimeout(() => _closeJob(id), remaining)
}

function toggleClosePin(id) {
  const j = jobs.value.find(e => e.id === id)
  if (!j) return
  j._closePinned = !j._closePinned
  if (j._closePinned) {
    pauseClose(id)
  } else {
    resumeClose(id)
  }
}

function _makeCallbacks(id) {
  return {
    onLogPath: path => {
      const j = jobs.value.find(e => e.id === id)
      if (j) j.logPath = path
      const h = _sessionHistory.value.find(e => e.id === id)
      if (h) h.logPath = path
    },
    onLog: text => {
      const j = jobs.value.find(e => e.id === id)
      // Lines array is shared with sessionHistory entry — one push updates both.
      if (j) j.lines.push(text.trimEnd())
    },
    onDone: () => {
      const j = jobs.value.find(e => e.id === id)
      if (j) { j.status = 'done'; j._cancel = null }
      const h = _sessionHistory.value.find(e => e.id === id)
      if (h) { h.status = 'done'; if (!h.endedAt) h.endedAt = Date.now() }
      _scheduleClose(id, AUTOCLOSE_MS.done)
    },
    onError: msg => {
      const j = jobs.value.find(e => e.id === id)
      if (j) { j.status = 'error'; j._cancel = null; j.lines.push(`Error: ${msg}`) }
      const h = _sessionHistory.value.find(e => e.id === id)
      if (h) { h.status = 'error'; if (!h.endedAt) h.endedAt = Date.now() }
      // No auto-close — errors require explicit dismissal.
    },
    onConflict: blocking => {
      const j = jobs.value.find(e => e.id === id)
      if (j) {
        j.status = 'error'
        j._cancel = null
        j.lines.push(
          `Can't launch — ${blocking.join(', ')} ${blocking.length === 1 ? 'is' : 'are'} already running.` +
          ` These tools share a write group and can't run at the same time.`
        )
      }
      const h = _sessionHistory.value.find(e => e.id === id)
      if (h) { h.status = 'error'; if (!h.endedAt) h.endedAt = Date.now() }
      // No auto-close — treat conflicts like errors.
    },
  }
}

function _makeJobEntry(id, key) {
  return {
    id,
    key,
    status: 'running',
    lines: [],
    logPath: null,
    collapsed: false,
    _cancel: null,
    _closeTimer: null,
    _closeRemaining: 0,
    _closePinned: false,
    closeDuration: 0,
    closeAt: 0,
  }
}

async function _loadDiskHistory() {
  if (_diskHistoryLoaded) return
  _diskHistoryLoaded = true
  try {
    const r = await fetch('/api/history')
    if (!r.ok) return
    const entries = await r.json()
    const existingIds = new Set(_sessionHistory.value.map(h => h.id))
    // entries are newest-first; reverse so oldest goes at front of history
    for (const e of [...entries].reverse()) {
      if (!existingIds.has(e.id)) _sessionHistory.value.unshift(e)
    }
  } catch { /* best-effort — silently ignore on network error */ }
}

export function useJobs() {
  const runningJobKeys = computed(() =>
    jobs.value.filter(j => j.status === 'running').map(j => j.key)
  )

  function launch(job, params = {}) {
    const id = _nextId++
    const entry = _makeJobEntry(id, job.key)
    jobs.value.push(entry)
    // History entry shares the same lines array
    _sessionHistory.value.push({ id, key: job.key, status: 'running', startedAt: Date.now(), endedAt: null, lines: entry.lines, logPath: null })
    const { cancel } = runJob({ tool: job.key, params }, _makeCallbacks(id))
    const j = jobs.value.find(e => e.id === id)
    if (j) j._cancel = cancel
  }

  function launchReports(reports, formats, useLast = false) {
    const label = reports.length === 1 ? reports[0].key : `reports (${reports.length})`
    const id = _nextId++
    const entry = _makeJobEntry(id, label)
    jobs.value.push(entry)
    _sessionHistory.value.push({ id, key: label, status: 'running', startedAt: Date.now(), endedAt: null, lines: entry.lines })
    const payload = { reports: reports.map(r => r.key), formats }
    if (useLast) payload.reuse_data = 'last'
    const { cancel } = runJob(payload, _makeCallbacks(id))
    const j = jobs.value.find(e => e.id === id)
    if (j) j._cancel = cancel
  }

  function cancelJob(id) {
    const j = jobs.value.find(e => e.id === id)
    if (!j) return
    j._cancel?.()
    j.status = 'cancelled'
    j._cancel = null
    j.lines.push('— cancelled —')
    const h = _sessionHistory.value.find(e => e.id === id)
    if (h) { h.status = 'cancelled'; if (!h.endedAt) h.endedAt = Date.now() }
    _scheduleClose(id, AUTOCLOSE_MS.cancelled)
  }

  function closeJob(id) { _closeJob(id) }

  function toggleCollapse(id) {
    const j = jobs.value.find(e => e.id === id)
    if (j) j.collapsed = !j.collapsed
  }

  // Remove all finished/cancelled/errored entries from session history and
  // close their corresponding panes. Running jobs are left untouched.
  function clearHistory() {
    const runningIds = new Set(
      jobs.value.filter(j => j.status === 'running').map(j => j.id)
    )
    // Close any open (non-running) panes that belong to cleared entries
    jobs.value = jobs.value.filter(j => runningIds.has(j.id))
    _sessionHistory.value = _sessionHistory.value.filter(h => runningIds.has(h.id))
  }

  // Reopen a past job in the JobRunner pane without any auto-close timer.
  // If already open, just scroll to it.
  function reopenJob(id) {
    const h = _sessionHistory.value.find(e => e.id === id)
    if (!h) return
    const alreadyOpen = jobs.value.some(e => e.id === id)
    if (!alreadyOpen) {
      jobs.value.push({
        id:             h.id,
        key:            h.key,
        status:         h.status,
        lines:          h.lines,   // same reference — shows all stored output
        logPath:        h.logPath,
        collapsed:      false,
        _cancel:        null,
        _closeTimer:    null,
        _closeRemaining: 0,
        _closePinned:   false,
        closeDuration:  0,         // no countdown — stays open until manually closed
        closeAt:        0,
      })
    }
    _scrollToId.value = id
  }

  return {
    jobs,
    runningJobKeys,
    sessionHistory: _sessionHistory,
    scrollToJobId: _scrollToId,
    launch,
    launchReports,
    cancelJob,
    closeJob,
    toggleCollapse,
    pauseClose,
    resumeClose,
    toggleClosePin,
    reopenJob,
    clearHistory,
    loadDiskHistory: _loadDiskHistory,
  }
}
