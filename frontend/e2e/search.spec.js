// JQL search view (epic #297, issue #302). Verification points from the
// issue: header-click sorting re-orders the displayed rows (asc/desc toggle)
// WITHOUT issuing a new API call; the "sorted locally" hint appears when the
// limit truncated the result set; parse errors render inline with the caret
// anchored at the reported position.
import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { mockApi, seedAuthedSession } from './support.js'

const ROW = (iid, title, weight, due) => ({
  id: String(1000 + iid), iid, type: 'issue', title, state: 'opened',
  labels: ['type::feature'], assignees: ['alice'], author: 'bob',
  milestone: null, milestone_due: null, iteration: null,
  weight, business_value: null, start_date: null, due_date: due,
  created_at: '2026-03-01T10:00:00Z', updated_at: '2026-07-25T00:00:00Z',
  closed_at: null, parent_iid: null, namespace_path: 'portfolio/team-a',
  web_url: `https://gitlab.example/team-a/-/work_items/${iid}`,
  description: null,
})

// Fetch order (the query's ORDER BY due ASC): 12, 11, 14 — deliberately not
// sorted by weight, so a weight header sort visibly re-orders.
const ITEMS = [
  ROW(12, 'Fix gateway timeout defect', 2, '2026-08-20'),
  ROW(11, 'Implement payment gateway API', 5, '2026-09-01'),
  ROW(14, 'Unassigned backlog item', 9, null),
]

function envelope(items, { limit = 100, truncated = false } = {}) {
  return { query: '', items, count: items.length, limit, truncated,
           plan: { push_down: true, variables: {}, sort: null,
                   client_sort: [], pages_fetched: 1, scanned: items.length } }
}

async function openSearch(page, queryResponse) {
  await seedAuthedSession(page)
  await mockApi(page)                       // /api/config etc. for the shell
  page.queryCalls = 0
  await page.route('**/api/query', (route) => {
    page.queryCalls++
    return route.fulfill(queryResponse)
  })
  await page.goto('/app/search')
  await expect(page.locator('.search-page')).toBeVisible()
}

async function run(page, jql) {
  await page.locator('.query-input').fill(jql)
  await page.locator('.run-btn').click()
}

function columnCells(page, nth) {
  // nth is 1-based CSS nth-child of the column
  return page.locator(`.results-table tbody td:nth-child(${nth})`)
}

test.describe('JQL search view (#302)', () => {

  test('runs a query and renders rows in fetch order with linked titles', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS) })
    await run(page, 'state = opened ORDER BY due ASC')

    await expect(page.locator('.results-table tbody tr')).toHaveCount(3)
    await expect(columnCells(page, 1)).toHaveText(['12', '11', '14'])
    const link = page.locator('.cell-title a').first()
    await expect(link).toHaveAttribute('href', 'https://gitlab.example/team-a/-/work_items/12')
    await expect(link).toHaveAttribute('target', '_blank')
    expect(page.queryCalls).toBe(1)
  })

  test('header click re-sorts client-side, toggles asc/desc, no new API call', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS) })
    await run(page, 'state = opened ORDER BY due ASC')
    await expect(page.locator('.results-table tbody tr')).toHaveCount(3)

    // Sort by Weight (6th column): asc → 2, 5, 9
    await page.getByRole('button', { name: /^Weight/ }).click()
    await expect(columnCells(page, 6)).toHaveText(['2', '5', '9'])
    // Toggle → desc
    await page.getByRole('button', { name: /^Weight/ }).click()
    await expect(columnCells(page, 6)).toHaveText(['9', '5', '2'])
    // Due sort keeps the empty due date last even ascending
    await page.getByRole('button', { name: /^Due/ }).click()
    await expect(columnCells(page, 10)).toHaveText(['2026-08-20', '2026-09-01', '—'])

    // Re-sorting is a client-side re-sort of the fetched set only
    expect(page.queryCalls).toBe(1)

    // Reset returns to the fetch order defined by the query's ORDER BY
    await page.locator('.meta-reset').click()
    await expect(columnCells(page, 1)).toHaveText(['12', '11', '14'])
  })

  test('capped result set shows the "sorted locally" hint only once a header sort is active', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS, { limit: 3, truncated: true }) })
    await run(page, 'state = opened')
    await expect(page.locator('.results-table tbody tr')).toHaveCount(3)

    await expect(page.locator('.meta-truncated')).toContainText('capped at limit 3')
    await expect(page.locator('.meta-hint')).toHaveCount(0)

    await page.getByRole('button', { name: /^Weight/ }).click()
    await expect(page.locator('.meta-hint')).toContainText('sorted locally — first 3 results')

    await page.locator('.meta-reset').click()
    await expect(page.locator('.meta-hint')).toHaveCount(0)
  })

  test('syntax errors render inline with the caret at the reported position', async ({ page }) => {
    const jql = 'state = opened AND'
    await openSearch(page, {
      status: 400,
      json: { detail: { kind: 'syntax', message: 'Expected a field name',
                        position: 18, found: 'end of query',
                        expected: ['field name', '('] } },
    })
    await run(page, jql)

    const box = page.locator('.error-box')
    await expect(box).toBeVisible()
    await expect(box.locator('.error-lead')).toHaveText('Syntax error')
    await expect(box.locator('.error-msg')).toContainText('Expected a field name')
    await expect(box.locator('.error-expected code')).toHaveText(['field name', '('])
    // The echoed query plus a caret line anchored at offset 18
    await expect(box.locator('.error-query')).toHaveText(jql + '\n' + ' '.repeat(18) + '^')
  })

  test('semantic errors and empty results have their own states', async ({ page }) => {
    await openSearch(page, {
      status: 400,
      json: { detail: { kind: 'semantic',
                        message: "Unknown field 'flavor'. Valid fields: state, type" } },
    })
    await run(page, 'flavor = chocolate')
    await expect(page.locator('.error-lead')).toHaveText('Query error')
    await expect(page.locator('.error-msg')).toContainText("Unknown field 'flavor'")

    await page.unroute('**/api/query')
    await page.route('**/api/query', (route) => route.fulfill({ json: envelope([]) }))
    await run(page, 'state = closed AND weight >= 99')
    await expect(page.locator('.search-empty .empty-lead')).toHaveText('No matching work items')
  })
})

// Help panel + expandable editor (issue #302 follow-up): the search bar's
// far-right icons mirror Jira's — expand for larger query editing, and a
// help panel whose examples are built from the live /api/query/fields
// vocabulary so they copy-paste against real data in the configured group.
test.describe('JQL search help panel (#302)', () => {

  test('header shows the queried group slug from /api/config', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS) })
    await expect(page.locator('.search-sub .scope-slug')).toHaveText('portfolio/test-group')
  })

  test('help opens with the field vocabulary and scope-aware examples', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS) })
    await page.locator('.help-btn').click()
    await expect(page.locator('.help-panel')).toBeVisible()
    // Field table renders the taxonomy values fetched from the server
    await expect(page.locator('.help-fields')).toContainText('piid')
    await expect(page.locator('.help-fields .value-chip').filter({ hasText: '2026Q3' })).toBeVisible()
    // Examples are assembled from those same values — real data, not doc lore
    await expect(page.locator('.help-examples .example-btn')
      .filter({ hasText: 'piid = 2026Q3 AND state = opened' })).toBeVisible()
    await expect(page.locator('.help-examples .example-btn')
      .filter({ hasText: 'piid IN (2026Q3, 2026Q4) ORDER BY weight DESC' })).toBeVisible()
  })

  test('clicking a help example fills the box, closes help, and runs', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS) })
    await page.locator('.help-btn').click()
    await page.locator('.help-examples .example-btn')
      .filter({ hasText: 'piid = 2026Q3 AND state = opened' }).click()
    await expect(page.locator('.help-panel')).toHaveCount(0)
    await expect(page.locator('.query-input')).toHaveValue('piid = 2026Q3 AND state = opened')
    await expect(page.locator('.results-table tbody tr')).toHaveCount(3)
    expect(page.queryCalls).toBe(1)
  })

  test('expand toggle swaps to a multi-line editor and keeps the query', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS) })
    await page.locator('.query-input').fill('state = opened')
    await page.locator('.expand-btn').click()
    const area = page.locator('textarea.query-textarea')
    await expect(area).toBeVisible()
    await expect(area).toHaveValue('state = opened')      // same model, no loss
    await area.fill('state = opened\nAND weight >= 5\nORDER BY due ASC')
    // Collapse and re-expand: the model keeps the multi-line text (a
    // single-line <input> can't display newlines, but must not eat them).
    await page.locator('.expand-btn').click()
    await page.locator('.expand-btn').click()
    await expect(page.locator('textarea.query-textarea')).toHaveValue(
      'state = opened\nAND weight >= 5\nORDER BY due ASC')
  })
})

// Export buttons (issue #302 follow-up): CSV mirrors the CLI csv format and
// the displayed order (local sort included); JSON is the untouched envelope.
test.describe('JQL search export (#302)', () => {

  test('CSV export downloads the displayed rows, local sort included', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS) })
    await run(page, 'state = opened ORDER BY due ASC')
    // Sort by weight so the export order provably follows the display
    await page.locator('.th-btn', { hasText: 'Weight' }).click()
    const [ download ] = await Promise.all([
      page.waitForEvent('download'),
      page.locator('.export-btn', { hasText: 'CSV' }).click(),
    ])
    expect(download.suggestedFilename()).toMatch(/^jql-results-.*\.csv$/)
    const text = readFileSync(await download.path(), 'utf-8')
    const lines = text.trim().split('\r\n')
    expect(lines[0].split(',').slice(0, 3)).toEqual(['id', 'iid', 'type'])
    // Weight-ascending display order: iids 12 (2), 11 (5), 14 (9)
    const iids = lines.slice(1).map(l => l.split(',')[1])
    expect(iids).toEqual(['12', '11', '14'])
    expect(lines[1]).toContain('type::feature')
  })

  test('JSON export downloads the exact result envelope', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS) })
    await run(page, 'state = opened')
    const [ download ] = await Promise.all([
      page.waitForEvent('download'),
      page.locator('.export-btn', { hasText: 'JSON' }).click(),
    ])
    expect(download.suggestedFilename()).toMatch(/^jql-results-.*\.json$/)
    const body = JSON.parse(readFileSync(await download.path(), 'utf-8'))
    expect(body.count).toBe(3)
    expect(body.items.map(i => i.iid)).toEqual([12, 11, 14])  // fetch order, not display
    expect(body.plan).toBeTruthy()
  })
})
