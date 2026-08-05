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

// ── JQL search (epic #297, issue #302) ──────────────────────────────────────
// Run a JQL query live against GitLab through the same run_jql() entry point
// as the CLI tool. Success resolves to run_jql's envelope (items / count /
// limit / truncated / plan). Failures throw an Error carrying `.status` and
// the server's structured `.detail` ({kind, message, and for syntax errors
// position/found/expected}) so the search view can render parse errors
// inline, anchored at the reported position.
export async function postQuery(jql, limit) {
  const r = await fetch('/api/query', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ jql, limit }),
  })
  const body = await r.json().catch(() => ({}))
  if (!r.ok) {
    const detail = body.detail && typeof body.detail === 'object' ? body.detail : null
    const err = new Error(
      (detail && detail.message) ||
      (typeof body.detail === 'string' ? body.detail : `POST /api/query: ${r.status}`),
    )
    err.status = r.status
    err.detail = detail
    throw err
  }
  return body
}

// The JQL field vocabulary behind the search help panel — names, aliases,
// and the taxonomy value lists from the live config. Degrades to [] so the
// help still renders its static syntax reference without a server.
export async function getQueryFields() {
  try {
    const r = await fetch('/api/query/fields')
    if (!r.ok) return []
    return (await r.json()).fields || []
  } catch {
    return []
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

// ── Durable background jobs (issue #214) ────────────────────────────────────
// These jobs run as server-owned subprocesses whose state lives on disk, so
// they survive refreshes, re-logins, extra tabs, and server restarts. The
// useDurableJobs composable drives these; deploy/report UIs (#215/#219) consume
// that composable rather than calling these directly.

// Launch a durable job. `payload` is the report/tool run shape:
// { tool, params }, { report, formats, reuse_data }, or { reports, ... }.
// Returns the manifest. A 409 (a conflicting write tool is already running)
// throws an Error carrying `.conflict` and the `.blocking` job list so callers
// can render the parallelism guard instead of a generic failure.
export async function launchJob(payload) {
  const r = await fetch('/api/jobs', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(payload),
  })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    const detail = body.detail
    if (r.status === 409) {
      const err = new Error('conflict')
      err.conflict = true
      err.blocking = (detail && detail.blocking) || []
      throw err
    }
    throw new Error(typeof detail === 'string' ? detail : `POST /api/jobs: ${r.status}`)
  }
  return r.json()
}

// All durable jobs (live + recent), newest first.
export async function listJobs() {
  const r = await fetch('/api/jobs')
  if (!r.ok) throw new Error(`GET /api/jobs: ${r.status}`)
  return r.json()
}

// One job's manifest plus the log tail from `offset` bytes. The returned
// `offset` is the position to pass on the next poll to resume streaming.
export async function getJob(id, offset = 0) {
  const r = await fetch(`/api/jobs/${encodeURIComponent(id)}?offset=${offset}`)
  if (!r.ok) throw new Error(`GET /api/jobs/${id}: ${r.status}`)
  return r.json()
}

// Explicitly cancel a running job. No-op server-side on an already-finished job.
export async function cancelJob(id) {
  const r = await fetch(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
  if (!r.ok) throw new Error(`POST /api/jobs/${id}/cancel: ${r.status}`)
  return r.json()
}

// ── Deploy Options (epic #134, issue #215) ──────────────────────────────────
// Live per-target deploy status for the Run Reports Deploy Options section. The
// dialog polls this on the shared 3s cadence while it's visible. Degrades to a
// safe all-"unknown" shape on failure so the section still renders.
export async function getDeployStatus() {
  const fallback = {
    s3:  { state: 'unknown', url: null },
    ecs: { state: 'unknown', url: null },
    eks: { state: 'unknown', url: null },
  }
  try {
    const r = await fetch('/api/deploy/status')
    if (!r.ok) return fallback
    return r.json()
  } catch {
    return fallback
  }
}

// Launch a durable deploy/destroy job for a target. Returns the job manifest;
// the caller adopts it into the job runner for live-log + reattach. `body` may
// carry a `{ bucket }` for an S3 publish (issue #225).
export async function launchDeploy(target, action = 'deploy', body = null) {
  const init = { method: 'POST' }
  if (body) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  const r = await fetch(`/api/deploy/${encodeURIComponent(target)}/${encodeURIComponent(action)}`, init)
  if (!r.ok) {
    const b = await r.json().catch(() => ({}))
    throw new Error(b.detail || `POST /api/deploy/${target}/${action}: ${r.status}`)
  }
  return r.json()
}

// Bucket choices for the S3 deploy selector (issue #225): existing buckets, the
// current default, the account id, and a suggested base name. Resilient — the
// server returns empty/None on any failure so the dialog still works.
export async function getS3Buckets() {
  const fallback = { buckets: [], default: null, account_id: null, suggested_base: 'nce-safe-sim-site' }
  try {
    const r = await fetch('/api/deploy/s3/buckets')
    if (!r.ok) return fallback
    return r.json()
  } catch {
    return fallback
  }
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
