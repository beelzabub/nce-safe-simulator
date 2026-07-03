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

// Projects discovered under the configured namespace/parent_group, used to
// populate the import-issues project picker. Like getGroups, the endpoint
// degrades to [] on any failure and we swallow network errors here so callers
// can fall back to free-text entry.
export async function getProjects() {
  try {
    const r = await fetch('/api/projects')
    if (!r.ok) return []
    return r.json()
  } catch {
    return []
  }
}

// Curated server config (safe subset — never the full config.json). The login
// page reads dod_banner_enabled from here; on any failure we default to
// showing the banner, the safe direction for a consent notice.
export async function getConfig() {
  try {
    const r = await fetch('/api/config')
    if (!r.ok) return { dod_banner_enabled: true }
    return r.json()
  } catch {
    return { dod_banner_enabled: true }
  }
}

// ── Auth session (epic #135, issue #157) ────────────────────────────────────
// All three degrade to safe shapes on network failure: session degrades to
// method "none" (cosmetic front door, app shell still reachable — matching
// the pre-gate behavior when the API is down), login degrades to rejected.

export async function getSession() {
  try {
    const r = await fetch('/api/auth/session')
    if (!r.ok) return { authenticated: false, method: 'none' }
    return r.json()
  } catch {
    return { authenticated: false, method: 'none' }
  }
}

export async function postLogin(username, password) {
  try {
    const r = await fetch('/api/auth/login', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ username, password }),
    })
    if (!r.ok) return { authenticated: false }
    return r.json()
  } catch {
    return { authenticated: false }
  }
}

export async function postLogout() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' })
  } catch {
    /* logging out of a dead server is still logged out */
  }
}

// Login-page background slideshow (epic #135). The server returns a shuffled
// list — images[0] is the random initial background, the rest are the lazy
// rotation pool. Degrades to the fallback shape on any failure so the login
// page always renders (the client then uses its bundled hero image).
export async function getAuthBackgrounds() {
  const fallback = { rotation_seconds: 15, fallback: true, images: [] }
  try {
    const r = await fetch('/api/auth/backgrounds')
    if (!r.ok) return fallback
    return r.json()
  } catch {
    return fallback
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
