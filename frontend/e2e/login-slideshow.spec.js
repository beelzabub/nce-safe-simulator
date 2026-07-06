// Issue #187: the login slideshow carries subtle left/right chevrons so a
// viewer can step through the background imagery instead of only waiting for
// the auto-rotation.
import { test, expect } from '@playwright/test'
import { mockApi } from './support.js'

// A 1×1 GIF that loads instantly — the view only rotates to backgrounds whose
// preload resolved, so the pool needs real, loadable image data. Distinct
// fragments make two separate pool entries out of the same bytes.
const GIF = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'

test.describe('login slideshow navigation (#187)', () => {
  test.beforeEach(async ({ page }) => {
    // Pre-acknowledge the DoD banner so it doesn't sit over the slideshow (the
    // chevrons are intentionally hidden while the banner is up).
    await page.addInitScript(() => sessionStorage.setItem('nce.auth.dodBannerAccepted', '1'))
    await mockApi(page)
    // Serve a two-image rotation (mockApi's default is the single-image
    // fallback, which offers nothing to navigate between).
    await page.route('**/api/auth/backgrounds', (route) => route.fulfill({
      json: {
        rotation_seconds: 999,              // effectively no auto-advance during the test
        fallback: false,
        images: [
          { url: `${GIF}#a`, credit: 'Alpha' },
          { url: `${GIF}#b`, credit: 'Bravo' },
        ],
      },
    }))
    await page.goto('/app/login')
    await expect(page.locator('.login-page')).toBeVisible()
  })

  test('chevrons step to the next/previous background', async ({ page }) => {
    const next = page.locator('.slide-nav--next')
    const prev = page.locator('.slide-nav--prev')

    // Both chevrons appear once the second slide has preloaded into the pool.
    await expect(next).toBeVisible()
    await expect(prev).toBeVisible()

    // The photo credit tracks the active slide, so it's the visible proof of
    // which background is showing.
    await expect(page.getByText('Alpha')).toBeVisible()

    await next.click()
    await expect(page.getByText('Bravo')).toBeVisible()

    await prev.click()
    await expect(page.getByText('Alpha')).toBeVisible()
  })

  test('a chevron press does not summon the sign-in card', async ({ page }) => {
    const next = page.locator('.slide-nav--next')
    await expect(next).toBeVisible()

    await next.click()
    // @click.stop keeps the page-level "summon on click" from firing.
    await expect(page.locator('.login-card')).toBeHidden()
    await expect(next).toBeVisible()   // still there to keep browsing
  })
})
