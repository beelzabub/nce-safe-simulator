export async function getTools() {
  const r = await fetch('/api/tools')
  if (!r.ok) throw new Error(`GET /api/tools: ${r.status}`)
  return r.json()
}

export async function getReports() {
  const r = await fetch('/api/reports')
  if (!r.ok) throw new Error(`GET /api/reports: ${r.status}`)
  return r.json()
}

export async function getFullConfig() {
  const r = await fetch('/api/config/full')
  if (!r.ok) throw new Error(`GET /api/config/full: ${r.status}`)
  return r.json()
}

export async function saveConfig(data) {
  const r = await fetch('/api/config/full', {
    method:  'PUT',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(data),
  })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail || `PUT /api/config/full: ${r.status}`)
  }
  return r.json()
}
