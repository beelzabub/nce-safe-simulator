import { ref, watch, onUnmounted } from 'vue'
import { getDeployStatus } from '../api.js'

// Live deploy status for the Run Reports Deploy Options section (issue #215).
//
// Mirrors the useServerStatus pattern: poll GET /api/deploy/status on the shared
// 3s cadence, but only WHILE the Deploy Options UI is visible — `active` is a
// ref/getter the dialog toggles so the poll stops the moment it closes. The
// server caches the underlying AWS reads, so this stays cheap.
const POLL_MS = 3000

const EMPTY = {
  s3:  { state: 'unknown', url: null },
  ecs: { state: 'unknown', url: null },
  eks: { state: 'unknown', url: null },
}

export function useDeployStatus(active) {
  const status  = ref({ ...EMPTY })
  const loading = ref(true)
  let timer = null

  async function refresh() {
    try {
      status.value = await getDeployStatus()
    } finally {
      loading.value = false
    }
  }

  function startPolling() {
    loading.value = true
    refresh()
    timer = setInterval(refresh, POLL_MS)
  }

  function stopPolling() {
    if (timer) clearInterval(timer)
    timer = null
  }

  watch(active, v => v ? startPolling() : stopPolling(), { immediate: true })
  onUnmounted(stopPolling)

  return { status, loading, refresh }
}
