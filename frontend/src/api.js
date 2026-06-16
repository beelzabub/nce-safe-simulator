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
