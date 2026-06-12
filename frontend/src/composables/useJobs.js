import { ref, computed } from 'vue'
import { runJob } from '../ws.js'

// Module-level state — singleton shared across all component instances.
const jobs = ref([])
let _nextId = 1

function _makeCallbacks(id) {
  return {
    onLog: text => {
      const j = jobs.value.find(e => e.id === id)
      if (j) j.lines.push(text.trimEnd())
    },
    onDone: () => {
      const j = jobs.value.find(e => e.id === id)
      if (j) { j.status = 'done'; j._cancel = null }
    },
    onError: msg => {
      const j = jobs.value.find(e => e.id === id)
      if (j) { j.status = 'error'; j._cancel = null; j.lines.push(`Error: ${msg}`) }
    },
    onConflict: blocking => {
      const j = jobs.value.find(e => e.id === id)
      if (j) { j.status = 'error'; j._cancel = null; j.lines.push(`Conflict — blocked by: ${blocking.join(', ')}`) }
    },
  }
}

export function useJobs() {
  const runningJobKeys = computed(() =>
    jobs.value.filter(j => j.status === 'running').map(j => j.key)
  )

  function launch(job, params = {}) {
    const id = _nextId++
    jobs.value.push({ id, key: job.key, status: 'running', lines: [], collapsed: false, _cancel: null })
    const { cancel } = runJob({ tool: job.key, params }, _makeCallbacks(id))
    const j = jobs.value.find(e => e.id === id)
    if (j) j._cancel = cancel
  }

  function launchReports(reports, formats) {
    const label = reports.length === 1 ? reports[0].key : `reports (${reports.length})`
    const id = _nextId++
    jobs.value.push({ id, key: label, status: 'running', lines: [], collapsed: false, _cancel: null })
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
  }

  function closeJob(id) {
    jobs.value = jobs.value.filter(j => j.id !== id)
  }

  function toggleCollapse(id) {
    const j = jobs.value.find(e => e.id === id)
    if (j) j.collapsed = !j.collapsed
  }

  return { jobs, runningJobKeys, launch, launchReports, cancelJob, closeJob, toggleCollapse }
}
