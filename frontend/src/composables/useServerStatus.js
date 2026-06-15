import { ref, watch, onUnmounted } from 'vue'

export function useServerStatus(active) {
  const serverJobs = ref([])
  let timer = null

  async function refresh() {
    try {
      const r = await fetch('/api/running')
      if (r.ok) serverJobs.value = await r.json()
    } catch { /* server unreachable — keep stale data */ }
  }

  function startPolling() {
    refresh()
    timer = setInterval(refresh, 3000)
  }

  function stopPolling() {
    clearInterval(timer)
    timer = null
  }

  watch(active, v => v ? startPolling() : stopPolling(), { immediate: true })
  onUnmounted(stopPolling)

  return { serverJobs, refresh }
}
