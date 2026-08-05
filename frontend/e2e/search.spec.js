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

function envelope(items, { limit = 100, truncated = false, total = null,
                           labelColors = {} } = {}) {
  return { query: '', items, count: items.length, limit, offset: 0, total,
           truncated, label_colors: labelColors,
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

  test('label chips honor GitLab colors, defaults for unmapped labels', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS, {
      labelColors: { 'type::feature': { color: '#cc0033', text_color: '#FFFFFF' } },
    }) })
    await run(page, 'state = opened')
    const chip = page.locator('.label-chip', { hasText: 'type::feature' }).first()
    await expect(chip).toHaveCSS('background-color', 'rgb(204, 0, 51)')
    await expect(chip).toHaveCSS('color', 'rgb(255, 255, 255)')
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

// Export buttons (issue #302 follow-up): CSV covers EVERY match — a
// result-limited page re-fetches with limit "all" first — in the displayed
// order (local sort included); JSON is the untouched page envelope.
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

// Configure Columns (issue #302 follow-up): the ⚙ popover toggles which
// flat-schema fields render; the choice persists in localStorage.
test.describe('JQL search Configure Columns (#302)', () => {

  test('toggling columns updates the table, persists across reload, resets to defaults', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS) })
    await run(page, 'state = opened')
    await expect(page.locator('.results-table thead th')).toHaveCount(10)

    await page.locator('.export-btn', { hasText: 'Columns' }).click()
    await page.locator('.cols-item', { hasText: 'Weight' }).click()
    await expect(page.locator('.results-table thead th')).toHaveCount(9)
    await expect(page.locator('.th-btn', { hasText: 'Weight' })).toHaveCount(0)

    await page.locator('.cols-item', { hasText: 'Milestone due' }).click()
    await expect(page.locator('.results-table thead th')).toHaveCount(10)
    await expect(page.locator('.th-btn', { hasText: 'Milestone due' })).toHaveCount(1)

    // The choice survives a reload (localStorage)
    await page.reload()
    await expect(page.locator('.search-page')).toBeVisible()
    await run(page, 'state = opened')
    await expect(page.locator('.th-btn', { hasText: 'Weight' })).toHaveCount(0)
    await expect(page.locator('.th-btn', { hasText: 'Milestone due' })).toHaveCount(1)

    // Reset restores the #302 default set
    await page.locator('.export-btn', { hasText: 'Columns' }).click()
    await page.locator('.cols-reset').click()
    await expect(page.locator('.results-table thead th')).toHaveCount(10)
    await expect(page.locator('.th-btn', { hasText: 'Weight' })).toHaveCount(1)
    await expect(page.locator('.th-btn', { hasText: 'Milestone due' })).toHaveCount(0)
  })

  test('the derived Project column shows the namespace leaf', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS) })
    await run(page, 'state = opened')
    await page.locator('.export-btn', { hasText: 'Columns' }).click()
    await page.locator('.cols-item', { hasText: /^\s*Project\s*$/ }).click()
    await expect(page.locator('.th-btn', { hasText: 'Project' })).toHaveCount(1)
    // ROW namespace_path is 'portfolio/team-a' — the leaf renders, 11th col
    await expect(columnCells(page, 11).first()).toHaveText('team-a')
  })

  test('the last remaining column cannot be unchecked', async ({ page }) => {
    await openSearch(page, { json: envelope(ITEMS) })
    await run(page, 'state = opened')
    await page.locator('.export-btn', { hasText: 'Columns' }).click()
    for (const label of ['IID', 'Type', 'State', 'Labels', 'Weight', 'Assignees', 'Created', 'Updated', 'Due']) {
      await page.locator('.cols-item', { hasText: new RegExp(`^\\s*${label}\\s*$`) }).click()
    }
    await expect(page.locator('.results-table thead th')).toHaveCount(1)
    await expect(page.locator('.cols-item', { hasText: 'Title' }).locator('input')).toBeDisabled()
  })
})

// Pagination (issue #302 follow-up): offset/limit page through one stable
// result sequence; Prev/Next re-run the query with a shifted window.
test.describe('JQL search pagination (#302)', () => {

  const FIVE = [
    ROW(21, 'Item twenty-one', 1, '2026-08-10'),
    ROW(22, 'Item twenty-two', 2, '2026-08-11'),
    ROW(23, 'Item twenty-three', 3, '2026-08-12'),
    ROW(24, 'Item twenty-four', 4, '2026-08-13'),
    ROW(25, 'Item twenty-five', 5, '2026-08-14'),
  ]

  async function openPaged(page) {
    await seedAuthedSession(page)
    await mockApi(page)
    page.queryCalls = 0
    await page.route('**/api/query', (route) => {
      page.queryCalls++
      const body = route.request().postDataJSON()
      const off = body.offset || 0
      const lim = body.limit === 'all' ? FIVE.length : (body.limit || 100)
      const slice = FIVE.slice(off, off + lim)
      return route.fulfill({ json: {
        query: body.jql, items: slice, count: slice.length,
        limit: body.limit === 'all' ? 'all' : lim, offset: off,
        total: FIVE.length,            // fully pushed down — always exact
        truncated: off + lim < FIVE.length,
        plan: { push_down: true, variables: {}, sort: null, client_sort: [],
                pages_fetched: 1, scanned: FIVE.length },
      } })
    })
    await page.goto('/app/search')
    await expect(page.locator('.search-page')).toBeVisible()
    await page.locator('.limit-input').fill('2')
  }

  test('next/prev page through windows and disable at the edges', async ({ page }) => {
    await openPaged(page)
    await run(page, 'state = opened ORDER BY iid ASC')
    await expect(columnCells(page, 1)).toHaveText(['21', '22'])
    await expect(page.locator('.pager-range')).toHaveText('1–2 of 5')
    await expect(page.locator('.pager-btn', { hasText: 'Prev' })).toBeDisabled()

    await page.locator('.pager-btn', { hasText: 'Next' }).click()
    await expect(columnCells(page, 1)).toHaveText(['23', '24'])
    await expect(page.locator('.pager-range')).toHaveText('3–4 of 5')

    await page.locator('.pager-btn', { hasText: 'Next' }).click()
    await expect(columnCells(page, 1)).toHaveText(['25'])
    await expect(page.locator('.pager-range')).toHaveText('5–5 of 5')
    await expect(page.locator('.pager-btn', { hasText: 'Next' })).toBeDisabled()

    await page.locator('.pager-btn', { hasText: 'Prev' }).click()
    await expect(columnCells(page, 1)).toHaveText(['23', '24'])
    expect(page.queryCalls).toBe(4)
  })

  test('a new Run resets to the first window', async ({ page }) => {
    await openPaged(page)
    await run(page, 'state = opened ORDER BY iid ASC')
    await page.locator('.pager-btn', { hasText: 'Next' }).click()
    await expect(page.locator('.pager-range')).toHaveText('3–4 of 5')
    await page.locator('.run-btn').click()
    await expect(page.locator('.pager-range')).toHaveText('1–2 of 5')
    await expect(columnCells(page, 1)).toHaveText(['21', '22'])
  })

  test('result summary shows the exact total on a capped page', async ({ page }) => {
    await openPaged(page)
    await run(page, 'state = opened ORDER BY iid ASC')
    await expect(page.locator('.results-meta > span').first()).toHaveText('2 of 5 results')
    // Exact total known — the vague "capped … more may match" note is gone
    await expect(page.locator('.meta-truncated')).toHaveCount(0)
  })

  test('CSV export on a capped page re-fetches uncapped and covers every match', async ({ page }) => {
    await openPaged(page)
    await run(page, 'state = opened ORDER BY iid ASC')
    await expect(columnCells(page, 1)).toHaveText(['21', '22'])

    const [ download ] = await Promise.all([
      page.waitForEvent('download'),
      page.locator('.export-btn', { hasText: 'CSV' }).click(),
    ])
    expect(page.queryCalls).toBe(2)           // the uncapped re-fetch
    const lines = readFileSync(await download.path(), 'utf-8').trim().split('\r\n')
    const iids = lines.slice(1).map(l => l.split(',')[1])
    expect(iids).toEqual(['21', '22', '23', '24', '25'])
  })

  test('JSON export stays the current page envelope', async ({ page }) => {
    await openPaged(page)
    await run(page, 'state = opened ORDER BY iid ASC')
    const [ download ] = await Promise.all([
      page.waitForEvent('download'),
      page.locator('.export-btn', { hasText: 'JSON' }).click(),
    ])
    expect(page.queryCalls).toBe(1)           // no re-fetch
    const body = JSON.parse(readFileSync(await download.path(), 'utf-8'))
    expect(body.items.map(i => i.iid)).toEqual([21, 22])
    expect(body.total).toBe(5)
  })
})
