import { expect } from '@playwright/test'

// Hermetic API surface: every /api route the SPA touches is mocked, so the
// suite needs only the Vite dev server — no Python backend, no GitLab.
export const TOOLS = [
  {
    key: 'validate-labels',
    description: 'Check that scoped labels exist and are consistent',
    readonly: true,
    params: [],
  },
  {
    key: 'populate-roam',
    description: 'Populate ROAM risk labels across open risks',
    readonly: false,
    parallelism_group: 'risk-writers',
    params: [
      { name: 'count',   prompt: 'How many risks', type: 'int',  default: 3,    optional: true },
      { name: 'dry_run', prompt: 'Dry run',        type: 'bool', default: true },
    ],
  },
]

export const REPORTS = [
  { key: 'portfolio-health', description: 'Portfolio health dashboard' },
  { key: 'risk-register',    description: 'ROAM risk register' },
]

export async function mockApi(page) {
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    const json = (body) => route.fulfill({ json: body })
    if (path === '/api/config')           return json({ dod_banner_enabled: true, wiki_url: '', grafana_url: '', deployment_type: '' })
    // auth.method "none": the gate falls back to its client-side session
    // flag, which seedAuthedSession pre-sets for the home-view tests
    if (path === '/api/auth/session')     return json({ method: 'none', authenticated: false })
    if (path === '/api/auth/login')       return json({ method: 'none', authenticated: true })
    if (path === '/api/auth/backgrounds') return json({ rotation_seconds: 15, fallback: true, images: [] })
    if (path === '/api/tools')            return json(TOOLS)
    if (path === '/api/reports')          return json(REPORTS)
    if (path === '/api/history')          return json([])
    if (path === '/api/runs')             return json([])
    if (path === '/api/running')          return json([])
    return json({})
  })

  // A launched job streams two log lines and finishes — enough to drive the
  // runner tab through running → done.
  await page.routeWebSocket('**/ws/run', (ws) => {
    ws.onMessage(() => {
      ws.send(JSON.stringify({ type: 'log', text: 'starting…' }))
      ws.send(JSON.stringify({ type: 'log', text: 'all checks passed' }))
      ws.send(JSON.stringify({ type: 'done' }))
    })
  })
}

// Pre-acknowledge the DoD banner and the session gate so home-view tests can
// deep-link to /app/ (the login flow has its own dedicated test).
export async function seedAuthedSession(page) {
  await page.addInitScript(() => {
    sessionStorage.setItem('nce.auth.accepted', '1')
    sessionStorage.setItem('nce.auth.dodBannerAccepted', '1')
  })
}

// True below the app's phone breakpoint (the drawer/overlay layout).
export function phoneLayout(page) {
  return page.evaluate(() => matchMedia('(max-width: 768px)').matches)
}

// True when the device reports a touch-first pointer — the media query all
// touch-target and iOS-zoom CSS keys off.
export function coarsePointer(page) {
  return page.evaluate(() => matchMedia('(pointer: coarse)').matches)
}

export async function expectNoHorizontalOverflow(page) {
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))
  expect(overflow.scrollWidth, 'page must not scroll horizontally').toBeLessThanOrEqual(overflow.innerWidth + 1)
}
