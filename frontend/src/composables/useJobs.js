import { ref, computed } from 'vue'
import { runJob } from '../ws.js'

// Module-level state — singleton shared across all component instances.
const jobs = ref([])
let _nextId = 1

export function useJobs() {
  const runningJobKeys = computed(() =>
    jobs.value.filter(j => j.status === 'running').map(j => j.key)
  )

  function launch(job, params = {}) {
    const id = _nextId++
    jobs.value.push({ id, key: job.key, status: 'running', lines: [], collapsed: false })

    runJob(
      { tool: job.key, params },
      {
        onLog: text => {
          const j = jobs.value.find(e => e.id === id)
          if (j) j.lines.push(text)
        },
        onDone: () => {
          const j = jobs.value.find(e => e.id === id)
          if (j) j.status = 'done'
        },
        onError: msg => {
          const j = jobs.value.find(e => e.id === id)
          if (j) { j.status = 'error'; j.lines.push(`\nError: ${msg}`) }
        },
        onConflict: blocking => {
          const j = jobs.value.find(e => e.id === id)
          if (j) { j.status = 'error'; j.lines.push(`Conflict — blocked by: ${blocking.join(', ')}`) }
        },
      }
    )
  }

  function closeJob(id) {
    jobs.value = jobs.value.filter(j => j.id !== id)
  }

  function launchReports(reports, formats) {
    const label = reports.length === 1
      ? reports[0].key
      : `reports (${reports.length})`
    const id = _nextId++
    jobs.value.push({ id, key: label, status: 'running', lines: [], collapsed: false })

    runJob(
      { reports: reports.map(r => r.key), formats },
      {
        onLog: text => {
          const j = jobs.value.find(e => e.id === id)
          if (j) j.lines.push(text)
        },
        onDone: () => {
          const j = jobs.value.find(e => e.id === id)
          if (j) j.status = 'done'
        },
        onError: msg => {
          const j = jobs.value.find(e => e.id === id)
          if (j) { j.status = 'error'; j.lines.push(`\nError: ${msg}`) }
        },
        onConflict: blocking => {
          const j = jobs.value.find(e => e.id === id)
          if (j) { j.status = 'error'; j.lines.push(`Conflict — blocked by: ${blocking.join(', ')}`) }
        },
      }
    )
  }

  function toggleCollapse(id) {
    const j = jobs.value.find(e => e.id === id)
    if (j) j.collapsed = !j.collapsed
  }

  return { jobs, runningJobKeys, launch, launchReports, closeJob, toggleCollapse }
}
