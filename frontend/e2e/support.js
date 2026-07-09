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

export const RUNS = [
  { date: '20260701', time: '120000', path: 'reports/20260701/120000',
    has_log: true, log_name: 'run.log', has_data: true, has_wiki: true },
]

export const WIKI_INDEX = [
  { slug: 'home', title: 'NCE — Portfolio Home', path: 'NCE — Portfolio Home',
    segments: ['NCE — Portfolio Home'], tier: null, tier_name: null },
  { slug: 'portfolio-health', title: 'Portfolio Health Dashboard',
    path: 'NCE — Portfolio Home/00 Executive Pulse/Portfolio Health Dashboard',
    segments: ['NCE — Portfolio Home', '00 Executive Pulse', 'Portfolio Health Dashboard'],
    tier: '00', tier_name: 'Executive Pulse' },
  { slug: 'risk-register', title: 'Risk Register',
    path: 'NCE — Portfolio Home/01 Program Management/Risk Register',
    segments: ['NCE — Portfolio Home', '01 Program Management', 'Risk Register'],
    tier: '01', tier_name: 'Program Management' },
]

export const PORTFOLIO = {
  snapshot: { date: '20260701', time: '120000', generated_at: '2026-07-01T12:00:00Z' },
  totals: { portfolio_epics: 13, needs_attention: 2, blocked_items: 2,
            blocked_weight: 21, blocked_weight_downstream: 13, blocked_weight_subtree: 21,
            blocked_business_value: 5, blocked_business_value_downstream: 5,
            blocked_business_value_subtree: 5, untyped_in_chains: 1 },
  portfolio_epics: [
    {
      epic: { id: 1, iid: 1, title: 'Modernize Fleet Telemetry', state: 'opened',
              type: 'Epic', web_url: 'https://gitlab.example/epics/1',
              labels: ['Epic', 'project::DO'], piid: 'PIID::2026Q3',
              planned_weight: 233, actual_weight: 90, business_value: 21,
              pct_complete: 38.6, pct_through_pi: 30 },
      flags: { blocked: true, behind_schedule: false },
      needs_attention: true,
      rollup: { blocked_count: 2,
                blocked_weight: 21, blocked_weight_downstream: 13, blocked_weight_subtree: 21,
                blocked_business_value: 5, blocked_business_value_downstream: 5,
                blocked_business_value_subtree: 5 },
      chains: [
        {
          nodes: [
            { id: 1, title: 'Modernize Fleet Telemetry', type: 'Epic', state: 'opened',
              web_url: 'https://gitlab.example/epics/1', labels: [], piid: 'PIID::2026Q3',
              planned_weight: 233, actual_weight: 90, business_value: 21,
              pct_complete: 38.6, pct_through_pi: 30, blocked: false },
            { id: 2, title: 'Sensor Ingest Capability', type: null, state: 'opened',
              web_url: 'https://gitlab.example/epics/2', labels: [], piid: 'PIID::2026Q3',
              planned_weight: 34, actual_weight: 12, business_value: 8,
              pct_complete: 20, pct_through_pi: 30, blocked: false },
            { id: 3, title: 'Parse NMEA feeds', type: 'Feature', state: 'opened',
              web_url: 'https://gitlab.example/epics/3', labels: [], piid: 'PIID::2026Q3',
              planned_weight: 13, actual_weight: 5, business_value: 5,
              pct_complete: 10, pct_through_pi: 30, blocked: true },
          ],
          blockers: [{ id: 6, title: 'Upgrade message bus', type: 'Feature',
                       item_type: 'Epic', web_url: 'https://gitlab.example/epics/6' }],
        },
        {
          nodes: [
            { id: 1, title: 'Modernize Fleet Telemetry', type: 'Epic', state: 'opened',
              web_url: 'https://gitlab.example/epics/1', labels: [], piid: 'PIID::2026Q3',
              planned_weight: 233, actual_weight: 90, business_value: 21,
              pct_complete: 38.6, pct_through_pi: 30, blocked: false },
            { id: 90, title: 'Deprecated Ingest Path', type: 'Feature', state: 'closed',
              web_url: 'https://gitlab.example/epics/90', labels: [], piid: 'PIID::2026Q3',
              planned_weight: 8, actual_weight: 8, business_value: 0,
              pct_complete: 100, pct_through_pi: 30, blocked: true },
          ],
          blockers: [{ id: 91, title: 'Retired firewall rule review', type: 'Issue',
                       item_type: 'Issue', web_url: 'https://gitlab.example/issues/91' }],
        },
      ],
    },
    {
      epic: { id: 7, iid: 7, title: 'Shipboard Cyber Hardening', state: 'opened',
              type: 'Epic', web_url: 'https://gitlab.example/epics/7',
              labels: ['Epic', 'project::RTSO'], piid: 'PIID::2026Q3',
              planned_weight: 144, actual_weight: 10, business_value: 2,
              pct_complete: 10, pct_through_pi: 60 },
      flags: { blocked: false, behind_schedule: true },
      needs_attention: true,
      rollup: { blocked_count: 0,
                blocked_weight: 0, blocked_weight_downstream: 0, blocked_weight_subtree: 0,
                blocked_business_value: 0, blocked_business_value_downstream: 0,
                blocked_business_value_subtree: 0 },
      chains: [],
    },
    {
      epic: { id: 5, iid: 5, title: 'Common Data Fabric', state: 'opened',
              type: 'Epic', web_url: 'https://gitlab.example/epics/5',
              labels: ['Epic', 'project::DO'], piid: 'PIID::2026Q3',
              planned_weight: 89, actual_weight: 70, business_value: 13,
              pct_complete: 80, pct_through_pi: 50 },
      flags: { blocked: false, behind_schedule: false },
      needs_attention: false,
      rollup: { blocked_count: 0,
                blocked_weight: 0, blocked_weight_downstream: 0, blocked_weight_subtree: 0,
                blocked_business_value: 0, blocked_business_value_downstream: 0,
                blocked_business_value_subtree: 0 },
      chains: [],
    },
    // Filler so the card list outgrows the pane — regression fixture for the
    // flex squeeze that crushed expanded cards and clipped their chains.
    ...Array.from({ length: 10 }, (_, i) => ({
      epic: { id: 100 + i, iid: 100 + i, title: `Healthy Epic ${i + 1}`, state: 'opened',
              type: 'Epic', web_url: `https://gitlab.example/epics/${100 + i}`,
              labels: ['Epic'], piid: 'PIID::2026Q3',
              planned_weight: 21, actual_weight: 5, business_value: 3,
              pct_complete: 60, pct_through_pi: 40 },
      flags: { blocked: false, behind_schedule: false },
      needs_attention: false,
      rollup: { blocked_count: 0,
                blocked_weight: 0, blocked_weight_downstream: 0, blocked_weight_subtree: 0,
                blocked_business_value: 0, blocked_business_value_downstream: 0,
                blocked_business_value_subtree: 0 },
      chains: [],
    })),
  ],
}

export async function mockApi(page) {
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    const json = (body) => route.fulfill({ json: body })
    if (path === '/api/config')           return json({ dod_banner_enabled: true, wiki_url: '', grafana_url: '', deployment_type: '', version: 'nce-abc1234' })
    // auth.method "none": the gate falls back to its client-side session
    // flag, which seedAuthedSession pre-sets for the home-view tests
    if (path === '/api/auth/session')     return json({ method: 'none', authenticated: false })
    if (path === '/api/auth/login')       return json({ method: 'none', authenticated: true })
    if (path === '/api/auth/backgrounds') return json({ rotation_seconds: 15, fallback: true, images: [] })
    if (path === '/api/tools')            return json(TOOLS)
    if (path === '/api/reports')          return json(REPORTS)
    if (path === '/api/history')          return json([])
    if (path === '/api/runs')             return json(RUNS)
    if (path === '/api/running')          return json([])
    if (path === '/api/runs/20260701/120000/wiki/index.json') return json(WIKI_INDEX)
    if (path.endsWith('/wiki/portfolio-health.json'))
      return json({ slug: 'portfolio-health', title: 'Portfolio Health Dashboard',
                    html: '<h1>Portfolio Health Dashboard</h1><table><tr><th>VS</th><th>Status</th></tr><tr><td>VS 01</td><td>Green</td></tr></table>' })
    if (path === '/api/analysis/portfolio') return json(PORTFOLIO)

    // Durable job engine (#219): a launch returns a running manifest; the first
    // log-tail poll streams two lines, the next reports it done — enough to
    // drive the runner tab through running → done.
    const method = route.request().method()
    const JOB_LOG = 'starting…\nall checks passed\n'
    const manifest = (state, extra = {}) => ({
      id: 'job-1', label: 'audit-hierarchy', kind: 'tool', params: {},
      state, started: '2026-07-09T00:00:00+00:00',
      finished: state === 'running' ? null : '2026-07-09T00:00:01+00:00',
      exit_code: state === 'done' ? 0 : null, ...extra,
    })
    if (path === '/api/jobs' && method === 'POST') return json(manifest('running'))
    if (path === '/api/jobs' && method === 'GET')  return json([])
    const jobMatch = path.match(/^\/api\/jobs\/([^/]+)$/)
    if (jobMatch && method === 'GET') {
      const offset = Number(new URL(route.request().url()).searchParams.get('offset') || 0)
      return offset === 0
        ? json(manifest('running', { log: JOB_LOG, offset: JOB_LOG.length, running: true }))
        : json(manifest('done',    { log: '', offset, running: false }))
    }
    if (path.match(/^\/api\/jobs\/[^/]+\/cancel$/) && method === 'POST')
      return json(manifest('cancelled', { log: '', offset: 0 }))

    return json({})
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
