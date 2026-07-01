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

// Groups discovered under the configured namespace/parent_group, used to
// populate the tool group picker. The endpoint degrades to [] on any failure,
// and we also swallow network errors here so callers can fall back to free-text.
export async function getGroups() {
  try {
    const r = await fetch('/api/groups')
    if (!r.ok) return []
    return r.json()
  } catch {
    return []
  }
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

// Upload a file the browser user picked (e.g. an import CSV/JSON). The server
// stores it and returns { path, filename, size }; the returned server path is
// then passed to a tool's file param (input_path) for the actual run.
export async function upload(file) {
  const form = new FormData()
  form.append('file', file)
  const r = await fetch('/api/upload', { method: 'POST', body: form })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail || `POST /api/upload: ${r.status}`)
  }
  return r.json()
}
