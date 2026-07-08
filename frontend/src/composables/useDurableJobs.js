import { ref, computed } from 'vue'
import { launchJob, listJobs, getJob, cancelJob } from '../api.js'

// Durable background jobs (issue #214).
//
// These jobs run as server-owned subprocesses; their state and logs live on
// disk. This composable is the client-side reattach machinery: it launches
// jobs, polls their log tail by byte offset, and — critically — re-adopts any
// job still running on the server when the page (re)loads, so a refresh, a
// re-login, or a second tab all pick the job back up instead of losing it.
//
// It deliberately owns no UI. The Deploy Options dialog (#215) and the report-
// run migration (#219) render on top of this shared state.

// Module-level singleton — one source of truth across all component instances.
const jobs = ref([])          // [{ ...manifest, text, offset, _timer }]
const _byId = new Map()       // id -> reactive job entry
let _reattached = false

const POLL_MS = 1000
const TERMINAL = new Set(['done', 'error', 'cancelled', 'unknown'])

function _isTerminal(state) {
  return TERMINAL.has(state)
}

function _upsert(manifest) {
  let entry = _byId.get(manifest.id)
  if (!entry) {
    entry = { ...manifest, text: '', offset: 0, _timer: null }
    _byId.set(manifest.id, entry)
    // newest-first, matching GET /api/jobs order
    jobs.value = [entry, ...jobs.value]
  } else {
    Object.assign(entry, manifest)
    // trigger reactivity on the array for consumers watching `jobs`
    jobs.value = [...jobs.value]
  }
  return entry
}

function _stopTail(entry) {
  if (entry._timer) {
    clearTimeout(entry._timer)
    entry._timer = null
  }
}

// Poll one job's log tail from its current offset until it reaches a terminal
// state. Idempotent: a job already being tailed is not double-polled.
function _tail(id) {
  const entry = _byId.get(id)
  if (!entry || entry._timer) return

  const tick = async () => {
    entry._timer = null
    let data
    try {
      data = await getJob(id, entry.offset)
    } catch {
      // transient error — retry on the next interval if still running
      if (!_isTerminal(entry.state)) entry._timer = setTimeout(tick, POLL_MS)
      return
    }
    const { log, offset, ...manifest } = data
    if (log) entry.text += log
    entry.offset = offset
    Object.assign(entry, manifest)
    jobs.value = [...jobs.value]

    if (!_isTerminal(entry.state)) {
      entry._timer = setTimeout(tick, POLL_MS)
    }
  }
  tick()
}

export function useDurableJobs() {
  const runningJobs = computed(() =>
    jobs.value.filter(j => !_isTerminal(j.state))
  )

  // Launch a durable job and begin tailing it. `payload` is the /ws/run shape:
  // { tool, params } or { report, formats, reuse_data }.
  async function launch(payload) {
    const manifest = await launchJob(payload)
    const entry = _upsert(manifest)
    _tail(entry.id)
    return entry
  }

  // Re-adopt jobs from the server on page load: populate the list and resume
  // tailing anything still running. Safe to call repeatedly (runs once).
  async function reattach() {
    if (_reattached) return
    _reattached = true
    let manifests = []
    try {
      manifests = await listJobs()
    } catch {
      _reattached = false // allow a later retry if the server was briefly down
      return
    }
    // oldest-last insertion keeps _upsert's newest-first ordering intact
    for (const m of [...manifests].reverse()) _upsert(m)
    for (const m of manifests) {
      if (!_isTerminal(m.state)) _tail(m.id)
    }
  }

  async function cancel(id) {
    const manifest = await cancelJob(id)
    if (manifest) _upsert(manifest)
    return manifest
  }

  // Split accumulated log text into display lines for a given job.
  function linesFor(id) {
    const entry = _byId.get(id)
    if (!entry) return []
    return entry.text.split('\n')
  }

  return {
    jobs,
    runningJobs,
    launch,
    reattach,
    cancel,
    linesFor,
  }
}
