import { ref, computed } from 'vue'
import { launchJob, listJobs, getJob, cancelJob as apiCancelJob, launchDeploy as apiLaunchDeploy } from '../api.js'
import { triggerDownload } from '../download.js'

// Report/tool runs on the durable job engine (issue #219).
//
// A launch goes through POST /api/jobs, which starts a subprocess.Popen child
// owned by the server; its state and log live on disk. This composable tails
// that log by byte offset and — critically — re-adopts any run still going on
// the server when the page (re)loads, so a refresh, a re-login, or a second tab
// reattach to the live output instead of killing it. Cancellation is the
// explicit POST /api/jobs/{id}/cancel call, never a side effect of a disconnect.
//
// The public surface (launch, launchReports, cancelJob, sessionHistory, the
// auto-close/collapse/pin pane state, reopenJob, clearHistory, loadDiskHistory)
// is unchanged so JobRunner / StatusSidebar / HomeView keep working; only the
// transport underneath moved from the retired /ws/run socket to the durable
// engine's reattach/tail primitives.

// Module-level state — singleton shared across all component instances.
const jobs = ref([])              // open panes (JobRunner renders these)
const _sessionHistory = ref([])   // persistent; lines shared with the pane entry
const _scrollToId = ref(null)     // JobRunner watches this to scroll-to and clear
let _syntheticId = 1              // ids for launches that never reached the server
let _diskHistoryLoaded = false
let _reattached = false
// Earliest durable-job start (ms). Disk-history reconstruction only adds runs
// OLDER than this, so a completed durable run isn't also listed from disk.
let _durableFloor = Infinity

const POLL_MS = 1000
const TERMINAL = new Set(['done', 'error', 'cancelled', 'unknown'])
const _offsets = new Map()        // id -> next log byte offset
const _timers = new Map()         // id -> poll timeout handle
const _userCancelled = new Set()  // ids the user explicitly cancelled
const _terminalHandled = new Set()// ids whose terminal transition was processed

// Terminal control codes are meaningful in a terminal but visually broken in a
// <pre> block; strip them and fold bare carriage returns into newlines — the
// same normalisation the retired in-thread writer did, now applied client-side
// to the raw subprocess log.
const _ANSI_ESC = /\x1b(?:\[[0-9;]*[A-Za-z]|[^[])/g

function _clean(text) {
  return text.replace(_ANSI_ESC, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n')
}

// Map a durable manifest state to the UI status vocabulary.
function _uiStatus(state) {
  if (state === 'running') return 'running'
  if (state === 'done') return 'done'
  if (state === 'cancelled') return 'cancelled'
  return 'error'   // error, unknown, or anything unexpected
}

// Download URLs we've already auto-started, so a given export file downloads at
// most once. Only ever populated from freshly tailed output — reattached or
// disk-restored history never re-fires an old link.
const _autoDownloaded = new Set()
const _DOWNLOAD_RE = /\/api\/download\/\S+/

function _maybeAutoDownload(text) {
  const m = _DOWNLOAD_RE.exec(text)
  if (!m) return
  const url = m[0]
  if (_autoDownloaded.has(url)) return
  _autoDownloaded.add(url)
  triggerDownload(url)
}

// Auto-close delays by terminal status. Errors stay open until manually
// dismissed — failures need eyes on them.
const AUTOCLOSE_MS = { done: 60_000, cancelled: 30_000 }

function _closeJob(id) {
  const j = jobs.value.find(e => e.id === id)
  if (j?._closeTimer) clearTimeout(j._closeTimer)
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
  if (j._closePinned) pauseClose(id)
  else resumeClose(id)
}

function _makeJobEntry(id, key) {
  return {
    id,
    key,
    status: 'running',
    lines: [],
    logPath: null,
    collapsed: false,
    _closeTimer: null,
    _closeRemaining: 0,
    _closePinned: false,
    closeDuration: 0,
    closeAt: 0,
  }
}

function _setStatus(id, status) {
  const j = jobs.value.find(e => e.id === id)
  if (j) j.status = status
  const h = _sessionHistory.value.find(e => e.id === id)
  if (h) h.status = status
}

function _setLogPath(id, path) {
  const j = jobs.value.find(e => e.id === id)
  if (j) j.logPath = path
  const h = _sessionHistory.value.find(e => e.id === id)
  if (h) h.logPath = path
}

// The report/tool run prints "  log → <path>" for its own rich on-disk log;
// point the "Log ↗" link there when it appears (the job log is the fallback).
function _detectLogPath(id, chunk) {
  const m = /(?:^|\n)\s*log → (\S+)/.exec(chunk)
  if (m) _setLogPath(id, m[1])
}

// Rebuild the shared lines array in place from the accumulated raw log, so both
// the open pane and the session-history entry (same array reference) update.
function _rebuildLines(rec) {
  const lines = _clean(rec._raw || '').split('\n')
  if (lines.length && lines[lines.length - 1] === '') lines.pop()
  const arr = rec.lines
  arr.length = 0
  for (let i = 0; i < lines.length; i++) arr.push(lines[i])
}

function _stopTail(id) {
  const t = _timers.get(id)
  if (t) { clearTimeout(t); _timers.delete(id) }
}

function _onTerminal(id, status) {
  if (_terminalHandled.has(id)) return
  _terminalHandled.add(id)
  const h = _sessionHistory.value.find(e => e.id === id)
  if (h && !h.endedAt) h.endedAt = Date.now()
  const ms = AUTOCLOSE_MS[status]
  if (ms) _scheduleClose(id, ms)   // errors have no delay — stay open
}

// Poll one durable job's log tail from its current offset until it reaches a
// terminal state. Idempotent per id: a job already being tailed is not
// double-polled.
function _tail(id) {
  if (_timers.has(id)) return
  const tick = async () => {
    _timers.delete(id)
    let data
    try {
      data = await getJob(id, _offsets.get(id) || 0)
    } catch {
      _timers.set(id, setTimeout(tick, POLL_MS))   // transient — retry
      return
    }
    const { log, offset } = data
    _offsets.set(id, offset)
    const hist = _sessionHistory.value.find(e => e.id === id)
    if (log && hist) {
      hist._raw = (hist._raw || '') + log
      _rebuildLines(hist)
      _detectLogPath(id, log)
      _maybeAutoDownload(log)
    }
    let status = _uiStatus(data.state)
    // A cancel we requested may still show "running" for a beat while SIGTERM
    // lands — don't flip the pane back out of its cancelled state.
    if (_userCancelled.has(id) && data.state === 'running') status = 'cancelled'
    _setStatus(id, status)

    if (!TERMINAL.has(data.state)) {
      _timers.set(id, setTimeout(tick, POLL_MS))
    } else {
      _onTerminal(id, _uiStatus(data.state))
    }
  }
  tick()
}

// Adopt a server manifest into the UI: always a history entry; a running job
// also opens a live pane and starts tailing. `openPane` forces a pane open even
// for a terminal job (used when a fresh launch failed to start).
function _adopt(manifest, { openPane = false } = {}) {
  const id = manifest.id
  if (_sessionHistory.value.some(e => e.id === id)) return
  const status = _uiStatus(manifest.state)
  const startedAt = manifest.started ? Date.parse(manifest.started) : Date.now()
  const endedAt = manifest.finished ? Date.parse(manifest.finished) : null
  const running = manifest.state === 'running'

  const hist = {
    id,
    key: manifest.label || manifest.kind,
    status,
    startedAt,
    endedAt,
    lines: [],
    logPath: `logs/jobs/${id}.log`,
    _raw: '',
    _durable: true,
    kind: manifest.kind,
    params: manifest.params || {},
  }
  _sessionHistory.value.push(hist)

  if (running || openPane) {
    const pane = _makeJobEntry(id, hist.key)
    pane.status = status
    pane.lines = hist.lines       // shared reference — one update drives both
    pane.logPath = hist.logPath
    pane.kind = manifest.kind
    pane.params = manifest.params || {}
    jobs.value.push(pane)
  }
  if (running) {
    _offsets.set(id, 0)
    _tail(id)
  }
  return hist
}

async function _loadDiskHistory() {
  if (_diskHistoryLoaded) return
  _diskHistoryLoaded = true
  try {
    const r = await fetch('/api/history')
    if (!r.ok) return
    const entries = await r.json()
    const existingIds = new Set(_sessionHistory.value.map(h => h.id))
    // entries are newest-first; reverse so oldest goes at the front of history
    for (const e of [...entries].reverse()) {
      if (existingIds.has(e.id)) continue
      // Skip runs a durable job already covers (avoid double-listing a report
      // run that is both a live manifest and an on-disk directory).
      if (e.startedAt >= _durableFloor) continue
      _sessionHistory.value.unshift(e)
    }
  } catch { /* best-effort — silently ignore on network error */ }
}

// Re-adopt durable jobs from the server on page load: repopulate history and
// resume tailing anything still running. Safe to call repeatedly (runs once).
async function _reattach() {
  if (_reattached) return
  _reattached = true
  let manifests = []
  try {
    manifests = await listJobs()
  } catch {
    _reattached = false   // allow a later retry if the server was briefly down
    return
  }
  for (const m of manifests) {
    const started = m.started ? Date.parse(m.started) : Date.now()
    if (started < _durableFloor) _durableFloor = started
  }
  // oldest-last insertion keeps newest-first history ordering
  for (const m of [...manifests].reverse()) _adopt(m)
}

function _pushSyntheticError(key, message) {
  const id = `local-${_syntheticId++}`
  const lines = [message]
  const hist = {
    id, key, status: 'error', startedAt: Date.now(), endedAt: Date.now(),
    lines, logPath: null, _raw: '',
  }
  _sessionHistory.value.push(hist)
  const pane = _makeJobEntry(id, key)
  pane.status = 'error'
  pane.lines = lines
  jobs.value.push(pane)
  _terminalHandled.add(id)   // already terminal — no auto-close (like an error)
}

async function _launchDurable(payload, key) {
  let manifest
  try {
    manifest = await launchJob(payload)
  } catch (err) {
    if (err && err.conflict) {
      const names = err.blocking || []
      _pushSyntheticError(
        key,
        `Can't launch — ${names.join(', ')} ${names.length === 1 ? 'is' : 'are'} already running.` +
        ` These tools share a write group and can't run at the same time.`,
      )
    } else {
      _pushSyntheticError(key, `Error: ${err?.message || 'launch failed'}`)
    }
    return
  }
  // Failed-to-start manifests come back already terminal — force a pane so the
  // error is visible; otherwise this opens the live pane and starts tailing.
  _adopt(manifest, { openPane: manifest.state !== 'running' })
}

// Launch a durable deploy/destroy job through POST /api/deploy (issue #217).
// Same UX as a report/tool run: it lands in the JobRunner as a live streaming
// card, so the deploy log (success or failure) is visible in a job window.
async function _launchDeploy(target, action, key) {
  let manifest
  try {
    manifest = await apiLaunchDeploy(target, action)
  } catch (err) {
    _pushSyntheticError(key, `Error: ${err?.message || 'deploy launch failed'}`)
    return
  }
  _adopt(manifest, { openPane: manifest.state !== 'running' })
}

export function useJobs() {
  const runningJobKeys = computed(() =>
    jobs.value.filter(j => j.status === 'running').map(j => j.key)
  )

  function launch(job, params = {}) {
    _launchDurable({ tool: job.key, params }, job.key)
  }

  function launchReports(reports, formats, useLast = false) {
    const label = reports.length === 1 ? reports[0].key : `reports (${reports.length})`
    const payload = reports.length === 1
      ? { report: reports[0].key, formats }
      : { reports: reports.map(r => r.key), formats }
    if (useLast) payload.reuse_data = 'last'
    _launchDurable(payload, label)
  }

  // Launch an app-driven deploy/destroy (S3/ECS/EKS) as a live JobRunner card.
  function launchDeploy(target, action = 'deploy') {
    _launchDeploy(target, action, `${target}-${action}`)
  }

  // Running deploy/destroy job for a target, if any — lets the Deployments
  // dialog reflect an in-flight job (kinds are `deploy`, `deploy:s3`, …).
  function runningDeployJob(target) {
    return jobs.value.find(j =>
      j.status === 'running' &&
      typeof j.kind === 'string' && j.kind.startsWith('deploy') &&
      j.params?.target === target
    )
  }

  function cancelJob(id) {
    // Explicit server-side cancel (SIGTERM → process group). No-op on an
    // already-finished job; a disconnect never triggers this.
    if (String(id).startsWith('local-')) return   // synthetic, never launched
    apiCancelJob(id).catch(() => { /* best-effort; the tail reflects the result */ })
    _userCancelled.add(id)
    _setStatus(id, 'cancelled')
    const h = _sessionHistory.value.find(e => e.id === id)
    if (h) {
      h.lines.push('— cancelled —')
      if (!h.endedAt) h.endedAt = Date.now()
    }
    // Let the tail run to the terminal manifest, then schedule the auto-close.
  }

  function closeJob(id) { _closeJob(id) }

  function toggleCollapse(id) {
    const j = jobs.value.find(e => e.id === id)
    if (j) j.collapsed = !j.collapsed
  }

  // Remove all finished entries from session history and close their panes.
  // Running jobs are left untouched.
  function clearHistory() {
    const runningIds = new Set(
      jobs.value.filter(j => j.status === 'running').map(j => j.id)
    )
    jobs.value = jobs.value.filter(j => runningIds.has(j.id))
    _sessionHistory.value = _sessionHistory.value.filter(h => runningIds.has(h.id))
  }

  // Reopen a past job in the JobRunner pane without any auto-close timer. For a
  // reattached durable job whose log wasn't streamed this session, lazily fetch
  // the full log so "View" shows the complete output.
  async function reopenJob(id) {
    const h = _sessionHistory.value.find(e => e.id === id)
    if (!h) return
    const alreadyOpen = jobs.value.some(e => e.id === id)
    if (!alreadyOpen) {
      jobs.value.push({
        id:              h.id,
        key:             h.key,
        status:          h.status,
        lines:           h.lines,   // same reference — shows all stored output
        logPath:         h.logPath,
        collapsed:       false,
        _closeTimer:     null,
        _closeRemaining: 0,
        _closePinned:    false,
        closeDuration:   0,         // no countdown — stays open until closed
        closeAt:         0,
      })
    }
    if (h._durable && h.lines.length === 0) {
      try {
        const data = await getJob(id, 0)
        h._raw = data.log || ''
        _rebuildLines(h)
      } catch { /* leave empty on failure */ }
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
    launchDeploy,
    runningDeployJob,
    cancelJob,
    closeJob,
    toggleCollapse,
    pauseClose,
    resumeClose,
    toggleClosePin,
    reopenJob,
    clearHistory,
    loadDiskHistory: _loadDiskHistory,
    reattach: _reattach,
  }
}
