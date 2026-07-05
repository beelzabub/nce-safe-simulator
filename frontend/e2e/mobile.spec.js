// Mobile usability suite (issue #160). Runs on every device project defined
// in playwright.config.js — iPhones, iPads, Android phones — and asserts the
// simulator is actually operable there: everything fits, everything critical
// is tappable, and the phone-specific drawer/overlay layouts engage.
import { test, expect } from '@playwright/test'
import {
  mockApi,
  seedAuthedSession,
  phoneLayout,
  coarsePointer,
  expectNoHorizontalOverflow,
} from './support.js'

const MIN_TAP = 40 // px — WCAG 2.5.5-ish floor; Apple HIG asks for 44 on primary actions

test.describe('login flow', () => {
  test('DoD banner and sign-in are usable by touch', async ({ page }) => {
    await mockApi(page)
    await page.goto('/app/')

    // Unauthenticated navigation lands on the login front door
    await expect(page).toHaveURL(/\/app\/login$/)

    // DoD banner precedes everything and must be acknowledgeable
    const ok = page.getByRole('button', { name: 'OK' })
    await expect(ok).toBeVisible()
    await expectNoHorizontalOverflow(page)
    if (await coarsePointer(page)) {
      const box = await ok.boundingBox()
      expect(box.height, 'banner OK button tap height').toBeGreaterThanOrEqual(44)
    }
    await ok.tap()
    await expect(ok).toBeHidden()

    // The form rests dissolved behind a "Sign in" whisper (#158); tapping it
    // (or anywhere on the page) materializes the card
    const whisper = page.locator('.whisper')
    await expect(whisper).toBeVisible()
    if (await coarsePointer(page)) {
      const box = await whisper.boundingBox()
      expect(box.height, 'whisper tap height').toBeGreaterThanOrEqual(44)
    }
    await whisper.tap()

    // Credential fields: reachable, fillable, and ≥16px so iOS Safari
    // doesn't zoom the page on focus
    const username = page.locator('input[name="username"]')
    const password = page.locator('input[name="password"]')
    await expect(username).toBeVisible()
    await username.fill('jamie')
    await password.fill('hunter2')
    if (await coarsePointer(page)) {
      for (const field of [username, password]) {
        const fontSize = await field.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))
        expect(fontSize, 'input font-size must not trigger iOS focus-zoom').toBeGreaterThanOrEqual(16)
      }
    }

    // scoped to the card: the whisper is also accessibly named "Sign in"
    const submit = page.locator('.login-card').getByRole('button', { name: 'Sign in' })
    await expect(submit).toBeVisible() // also covers short landscape viewports
    await submit.tap()

    await expect(page.locator('.nav-bar')).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })
})

test.describe('DoD banner re-consent (#163)', () => {
  // The banner ack lives in sessionStorage; only a real signed-in ->
  // signed-out transition (session TTL lapse, server restart) may clear it.

  async function mockExpiredBasicSession(page) {
    await mockApi(page)
    // Later-registered routes win: server-enforced mode, session gone.
    await page.route('**/api/auth/session', (route) =>
      route.fulfill({ json: { method: 'basic', authenticated: false } }))
  }

  test('session expiry -> guard redirect re-presents the banner', async ({ page }) => {
    await page.addInitScript(() => {
      sessionStorage.setItem('nce.auth.dodBannerAccepted', '1')
      sessionStorage.setItem('nce.auth.wasAuthenticated', '1')   // was signed in
    })
    await mockExpiredBasicSession(page)
    await page.goto('/app/')
    await expect(page).toHaveURL(/\/app\/login$/)
    await expect(page.getByRole('button', { name: 'OK' })).toBeVisible()
  })

  test('session expiry -> direct /login visit re-presents the banner', async ({ page }) => {
    await page.addInitScript(() => {
      sessionStorage.setItem('nce.auth.dodBannerAccepted', '1')
      sessionStorage.setItem('nce.auth.wasAuthenticated', '1')
    })
    await mockExpiredBasicSession(page)
    await page.goto('/app/login')
    await expect(page.getByRole('button', { name: 'OK' })).toBeVisible()
  })

  test('reloading /login before ever signing in does not re-nag', async ({ page }) => {
    await page.addInitScript(() => {
      sessionStorage.setItem('nce.auth.dodBannerAccepted', '1')   // no wasAuthenticated
    })
    await mockExpiredBasicSession(page)
    await page.goto('/app/login')
    await expect(page.locator('.whisper')).toBeVisible()
    await expect(page.getByRole('button', { name: 'OK' })).toBeHidden()
  })
})

test.describe('home workspace', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuthedSession(page)
    await mockApi(page)
    await page.goto('/app/')
    await expect(page.locator('.nav-bar')).toBeVisible()
  })

  test('layout matches the device class and never overflows', async ({ page }) => {
    await expectNoHorizontalOverflow(page)
    const sidebar = page.locator('.sidebar')
    if (await phoneLayout(page)) {
      // Phones: sidebar is a drawer, toggled from the nav bar
      await expect(page.locator('.jobs-btn')).toBeVisible()
      await expect(sidebar).toBeInViewport() // starts open so users see the job list
    } else {
      // Tablets and up keep the two-column desktop layout
      await expect(page.locator('.jobs-btn')).toBeHidden()
      await expect(sidebar).toBeInViewport()
      const box = await sidebar.boundingBox()
      expect(box.width).toBe(340)
    }
  })

  test('version badge shows bottom-right on tablets/desktop (#173)', async ({ page }) => {
    const badge = page.locator('.version-badge')
    if (await phoneLayout(page)) {
      await expect(badge).toBeHidden()   // corners are tap-targets on phones
      return
    }
    await expect(badge).toHaveText('nce-abc1234')
    const [box, viewport] = [await badge.boundingBox(), page.viewportSize()]
    expect(box.x + box.width, 'anchored right').toBeGreaterThan(viewport.width * 0.8)
    expect(box.y + box.height, 'anchored bottom').toBeGreaterThan(viewport.height * 0.9)
  })

  test('nav bar controls meet tap-target size', async ({ page }) => {
    test.skip(!(await coarsePointer(page)), 'touch-target rules only apply to coarse pointers')
    for (const selector of ['.status-btn', '.config-btn', '.help-btn', '.theme-btn', '.signout-btn']) {
      const box = await page.locator(selector).boundingBox()
      expect(box.height, `${selector} tap height`).toBeGreaterThanOrEqual(MIN_TAP)
      expect(box.width, `${selector} tap width`).toBeGreaterThanOrEqual(MIN_TAP)
    }
  })

  test('jobs drawer opens, closes, and launches a job (phones)', async ({ page }) => {
    test.skip(!(await phoneLayout(page)), 'drawer layout is phone-only')
    const sidebar = page.locator('.sidebar')

    // Starts open; a tap on the exposed strip of backdrop dismisses it
    // (position: the drawer covers the backdrop's center, so aim right of it)
    await expect(sidebar).toBeInViewport()
    const viewport = page.viewportSize()
    await page.locator('.sidebar-backdrop').tap({ position: { x: viewport.width - 5, y: 40 } })
    await expect(sidebar).not.toBeInViewport()

    // ☰ reopens it
    await page.locator('.jobs-btn').tap()
    await expect(sidebar).toBeInViewport()

    // Expand the read-only group and launch the no-param job
    await page.getByRole('button', { name: /Audit & Validation/ }).tap()
    await page.getByText('Validate Labels', { exact: true }).tap()

    // Drawer yields to the runner pane; the job streams to done
    await expect(sidebar).not.toBeInViewport()
    await expect(page.locator('.tab-label')).toHaveText('Validate Labels')
    await expect(page.locator('.badge--done')).toBeVisible()
    await expect(page.getByText('all checks passed')).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })

  test('status panel is a full-width overlay (phones)', async ({ page }) => {
    const statusSidebar = page.locator('.status-sidebar')
    await page.locator('.status-btn').tap()
    await expect(statusSidebar).toBeInViewport()
    // toHaveCSS retries, so the 0.2s open/close width transition can finish
    if (await phoneLayout(page)) {
      await expect(statusSidebar, 'status panel should span the phone screen')
        .toHaveCSS('width', `${page.viewportSize().width}px`)
    } else {
      await expect(statusSidebar).toHaveCSS('width', '280px') // desktop default
    }
    await statusSidebar.locator('.close-btn').tap()
    // collapsed = 0 content width; the desktop variant keeps its 1px border
    await expect.poll(async () => (await statusSidebar.boundingBox())?.width ?? 0)
      .toBeLessThanOrEqual(1)
  })

  test('tool parameter dialog fits the screen', async ({ page }) => {
    // Job list is reachable immediately: drawer starts open on phones,
    // sidebar is static on tablets/desktop
    await page.getByRole('button', { name: /ROAM Risk/ }).tap()
    await page.getByText('Populate ROAM', { exact: true }).tap()

    const dialog = page.locator('.overlay .dialog')
    await expect(dialog).toBeVisible()
    const [box, viewport] = [await dialog.boundingBox(), page.viewportSize()]
    expect(box.width).toBeLessThanOrEqual(viewport.width)
    expect(box.height).toBeLessThanOrEqual(viewport.height)
    if (await phoneLayout(page)) {
      expect(box.width, 'param dialog goes full-screen on phones').toBeGreaterThanOrEqual(viewport.width - 1)
    }
    await dialog.getByRole('button', { name: 'Cancel' }).tap()
    await expect(dialog).toBeHidden()
  })

  test('help dialog fits the screen', async ({ page }) => {
    await page.locator('.help-btn').tap()
    const dialog = page.locator('.overlay .dialog')
    await expect(dialog).toBeVisible()
    const [box, viewport] = [await dialog.boundingBox(), page.viewportSize()]
    expect(box.width).toBeLessThanOrEqual(viewport.width)
    expect(box.height).toBeLessThanOrEqual(viewport.height)
    if (await phoneLayout(page)) {
      expect(box.height, 'help dialog goes full-screen on phones').toBeGreaterThanOrEqual(viewport.height - 1)
    }
    await dialog.locator('.dialog-close').tap()
    await expect(dialog).toBeHidden()
  })

  test('report picker fits the screen', async ({ page }) => {
    await page.getByRole('button', { name: 'Run Reports…' }).tap()
    const dialog = page.locator('.overlay .dialog')
    await expect(dialog).toBeVisible()
    const [box, viewport] = [await dialog.boundingBox(), page.viewportSize()]
    expect(box.width).toBeLessThanOrEqual(viewport.width)
    expect(box.height).toBeLessThanOrEqual(viewport.height)
    await dialog.getByRole('button', { name: 'Cancel' }).tap()
    await expect(dialog).toBeHidden()
  })

  test('side panel tabs switch and persist (epic #165)', async ({ page }) => {
    // Tools is the default tab and hosts the job picker
    const tabs = page.locator('.side-panel .tab-btn')
    await expect(tabs).toHaveCount(3)
    await expect(page.locator('.picker')).toBeVisible()

    // Reports lists the mocked snapshot run; Analysis lists its tools
    await tabs.filter({ hasText: 'Reports' }).tap()
    await expect(page.locator('.reports-tab .run-select')).toBeVisible()
    await tabs.filter({ hasText: 'Analysis' }).tap()
    await expect(page.locator('.analysis-row .analysis-name')).toHaveText('Portfolio Explorer')

    // Active tab survives a reload (localStorage). On phones the drawer
    // starts open after load, so the panel is already visible.
    await page.reload()
    await expect(page.locator('.nav-bar')).toBeVisible()
    await expect(page.locator('.analysis-row .analysis-name')).toHaveText('Portfolio Explorer')

    // Back to Tools: picker is intact
    await page.locator('.side-panel .tab-btn').filter({ hasText: 'Tools' }).tap()
    await expect(page.locator('.picker')).toBeVisible()
  })

  test('reports tab opens a wiki page in the markdown viewer (#167)', async ({ page }) => {
    await page.locator('.side-panel .tab-btn').filter({ hasText: 'Reports' }).tap()

    // Page tree mirrors the wiki hierarchy from the mocked snapshot
    await expect(page.locator('.dir-label').filter({ hasText: '00 Executive Pulse' })).toBeVisible()
    await expect(page.locator('.dir-label').filter({ hasText: '01 Program Management' })).toBeVisible()

    // Filter narrows across the tree and keeps wiki context; × clears it
    await page.locator('.reports-filter .filter-input').fill('health')
    await expect(page.locator('.page-row')).toHaveCount(1)
    await expect(page.locator('.dir-label').filter({ hasText: '00 Executive Pulse' })).toBeVisible()
    await expect(page.locator('.dir-label').filter({ hasText: '01 Program Management' })).toHaveCount(0)
    await page.locator('.reports-filter .filter-clear').tap()
    await expect(page.locator('.page-row')).toHaveCount(3)

    // Run Reports is available here too, above the restored footer links
    const reportsTab = page.locator('.reports-tab')
    await expect(reportsTab.getByRole('button', { name: 'Run Reports…' })).toBeVisible()
    await expect(page.locator('.panel-footer .footer-link', { hasText: 'Quarto' })).toBeVisible()
    await reportsTab.getByRole('button', { name: 'Run Reports…' }).tap()
    const rpDialog = page.locator('.overlay .dialog')
    await expect(rpDialog).toBeVisible()
    await rpDialog.getByRole('button', { name: 'Cancel' }).tap()
    await expect(rpDialog).toBeHidden()

    await page.locator('.page-row', { hasText: 'Portfolio Health Dashboard' }).tap()

    // Main pane switches to the in-app viewer (drawer closes on phones)
    const view = page.locator('.md-view')
    await expect(view).toBeVisible()
    await expect(view.locator('.md-title')).toHaveText('Portfolio Health Dashboard')
    await expect(view.locator('.md-body table')).toBeVisible()
    await expectNoHorizontalOverflow(page)

    // Reset the persisted tab so later tests start from Tools
    await page.evaluate(() => localStorage.removeItem('nce.sidepanel.tab'))
  })

  test('portfolio explorer lists all epics and flags issues (#169)', async ({ page }) => {
    await page.locator('.side-panel .tab-btn').filter({ hasText: 'Analysis' }).tap()
    await page.locator('.analysis-row').tap()

    const pfx = page.locator('.pfx')
    await expect(pfx).toBeVisible()

    // Totals strip: whole portfolio, attention count, BV at risk
    await expect(pfx.locator('.stat-value').nth(0)).toHaveText('13')
    await expect(pfx.locator('.stat--attention .stat-value')).toHaveText('2')
    await expect(pfx.locator('.stat--bv .stat-value')).toHaveText('5')

    // Every portfolio epic renders; attention sorts first, healthy last
    const cards = pfx.locator('.epic-card')
    await expect(cards).toHaveCount(13)
    await expect(cards.nth(0).locator('.card-title')).toContainText('Modernize Fleet Telemetry')
    await expect(cards.nth(0).locator('.badge--blocked')).toContainText('2 blocked')
    await expect(cards.nth(1).locator('.badge--behind')).toBeVisible()
    await expect(cards.nth(2).locator('.badge--ok')).toHaveText('on track')

    // Top blocked card starts expanded: chain + blocked flag + blocker link
    await expect(cards.nth(0).locator('.chain-node.blocked .node-title')).toHaveText('Parse NMEA feeds')
    await expect(cards.nth(0).locator('.blocker-link')).toHaveText('Upgrade message bus')

    // Untyped epics render in chains with a badge and a data-quality hint (#174)
    await expect(cards.nth(0).locator('.untyped-flag')).toBeVisible()
    await expect(pfx.locator('.dq-hint')).toContainText('no epic-type label')
    await expectNoHorizontalOverflow(page)

    // The expanded card must not be crushed by the flex column when the
    // list outgrows the pane (clipped chains regression): its full content
    // fits inside its own box.
    const clipped = await cards.nth(0).evaluate(el => el.scrollHeight > el.clientHeight + 1)
    expect(clipped, 'expanded epic card is vertically clipped').toBe(false)

    // Collapse via the card head chevron
    await cards.nth(0).locator('.card-head').tap()
    await expect(cards.nth(0).locator('.chain-node')).toHaveCount(0)

    // #171 regression: each tab owns its main-area view — Tools brings the
    // job runner forward again, Reports shows its viewer pane.
    if (await phoneLayout(page)) await page.locator('.jobs-btn').tap()
    await page.locator('.side-panel .tab-btn').filter({ hasText: 'Tools' }).tap()
    await expect(page.locator('.runner')).toBeVisible()
    await expect(pfx).toBeHidden()
    await page.locator('.side-panel .tab-btn').filter({ hasText: 'Reports' }).tap()
    await expect(page.locator('.md-view')).toBeVisible()

    await page.evaluate(() => localStorage.removeItem('nce.sidepanel.tab'))
  })
})
