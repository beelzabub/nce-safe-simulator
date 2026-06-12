import { ref, computed } from 'vue'
import { runJob } from '../ws.js'

// Module-level state — singleton shared across all component instances.
const jobs = ref([])
let _nextId = 1

// Auto-close delays by terminal status.  Errors stay open until manually
// dismissed — failures need eyes on them.
const AUTOCLOSE_MS = { done: 60_000, cancelled: 30_000 }

// Module-level so _scheduleClose can reference it.
function _closeJob(id) {
  const j = jobs.value.find(e => e.id === id)
  if (j?._closeTimer) clearTimeout(j._closeTimer)
  jobs.value = jobs.value.filter(e => e.id !== id)
}

function _scheduleClose(id, ms) {
  const j = jobs.value.find(e => e.id === id)
  if (!j) return
  j.closeDuration = ms
  j._closeTimer = setTimeout(() => _closeJob(id), ms)
}

function _makeCallbacks(id) {
  return {
    onLog: text => {
      const j = jobs.value.find(e => e.id === id)
      if (j) j.lines.push(text.trimEnd())
    },
    onDone: () => {
      const j = jobs.value.find(e => e.id === id)
      if (j) { j.status = 'done'; j._cancel = null }
      _scheduleClose(id, AUTOCLOSE_MS.done)
    },
    onError: msg => {
      const j = jobs.value.find(e => e.id === id)
      if (j) { j.status = 'error'; j._cancel = null; j.lines.push(`Error: ${msg}`) }
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
      // No auto-close — treat conflicts like errors.
    },
  }
}

export function useJobs() {
  const runningJobKeys = computed(() =>
    jobs.value.filter(j => j.status === 'running').map(j => j.key)
  )

  function launch(job, params = {}) {
    const id = _nextId++
    jobs.value.push({ id, key: job.key, status: 'running', lines: [], collapsed: false, _cancel: null, _closeTimer: null, closeDuration: 0 })
    const { cancel } = runJob({ tool: job.key, params }, _makeCallbacks(id))
    const j = jobs.value.find(e => e.id === id)
    if (j) j._cancel = cancel
  }

  function launchReports(reports, formats) {
    const label = reports.length === 1 ? reports[0].key : `reports (${reports.length})`
    const id = _nextId++
    jobs.value.push({ id, key: label, status: 'running', lines: [], collapsed: false, _cancel: null, _closeTimer: null, closeDuration: 0 })
    const { cancel } = runJob({ reports: reports.map(r => r.key), formats }, _makeCallbacks(id))
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
    _scheduleClose(id, AUTOCLOSE_MS.cancelled)
  }

  function closeJob(id) { _closeJob(id) }

  function toggleCollapse(id) {
    const j = jobs.value.find(e => e.id === id)
    if (j) j.collapsed = !j.collapsed
  }

  return { jobs, runningJobKeys, launch, launchReports, cancelJob, closeJob, toggleCollapse }
}
