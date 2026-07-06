// Issue #185: the equivalent CLI command must stay reachable while a modal
// dialog is open — the docked CommandBar sits *under* the full-screen overlay,
// so each dialog now carries its own copy of the command strip — and the last
// command must persist on the docked bar after the dialog closes.
import { test, expect } from '@playwright/test'
import { mockApi, seedAuthedSession, phoneLayout } from './support.js'

test.describe('CLI command accessibility (#185)', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuthedSession(page)
    await mockApi(page)
    await page.goto('/app/')
    await expect(page.locator('.nav-bar')).toBeVisible()
  })

  test('tool dialog shows its live CLI command, which persists after close', async ({ page }) => {
    // Open the configurable ROAM tool → ToolParamDialog
    await page.getByRole('button', { name: /ROAM Risk/ }).click()
    await page.getByText('Populate ROAM', { exact: true }).click()

    const dialog = page.locator('.overlay .dialog')
    await expect(dialog).toBeVisible()

    // The command strip is *inside* the dialog, so it clears the overlay the
    // docked bar hides behind.
    const dialogCmd = dialog.locator('.dialog-cmd .cmd-text')
    await expect(dialogCmd).toBeVisible()
    await expect(dialogCmd).toHaveText(/python3 NceGitLab\.py -ut populate-roam/)
    await expect(dialog.locator('.dialog-cmd .cmd-copy')).toBeVisible()

    // It rebuilds live as params change: dry_run defaults on (the CLI default),
    // so toggling it off appends --dry_run=false.
    await expect(dialogCmd).not.toContainText('--dry_run=false')
    await dialog.locator('.toggle-label').click()
    await expect(dialogCmd).toContainText('--dry_run=false')

    // Close the dialog…
    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).toBeHidden()

    // …and the last command survives on the docked bar (desktop/tablet layout;
    // the bar is intentionally hidden on phones, where the run output carries it).
    if (!(await phoneLayout(page))) {
      const bar = page.locator('.cmd-bar .cmd-text')
      await expect(bar).toBeVisible()
      await expect(bar).toContainText('-ut populate-roam')
      await expect(bar).toContainText('--dry_run=false')
    }
  })

  test('report picker shows its CLI command inside the dialog', async ({ page }) => {
    await page.getByRole('button', { name: 'Run Reports…' }).first().click()

    const dialog = page.locator('.overlay .dialog')
    await expect(dialog).toBeVisible()

    // All reports are selected by default → one `-r` line per report.
    const dialogCmd = dialog.locator('.dialog-cmd .cmd-text')
    await expect(dialogCmd).toBeVisible()
    await expect(dialogCmd).toContainText('python3 NceGitLab.py -r')

    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).toBeHidden()
  })

  // Issue #187: the command strip stays a single line by default so a long
  // command can't stretch the layout; a toggle expands it on demand.
  test('the command collapses to one line with an expand toggle', async ({ page }) => {
    await page.getByRole('button', { name: 'Run Reports…' }).first().click()
    const dialog = page.locator('.overlay .dialog')
    await expect(dialog).toBeVisible()

    const text   = dialog.locator('.dialog-cmd .cmd-text')
    const toggle = dialog.locator('.dialog-cmd .cmd-expand')
    await expect(text).toBeVisible()

    // Collapsed by default — one line, whatever the viewport width.
    await expect(text).not.toHaveClass(/cmd-text--expanded/)
    expect(await text.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe('nowrap')

    // When the command is too long to fit, the toggle is offered and expands
    // the strip to the full wrapped command, then collapses it again.
    if (await text.evaluate((el) => el.scrollWidth - el.clientWidth > 1)) {
      await expect(toggle).toBeVisible()
      await expect(toggle).toHaveAttribute('aria-expanded', 'false')
      await toggle.click()
      await expect(text).toHaveClass(/cmd-text--expanded/)
      await expect(toggle).toHaveAttribute('aria-expanded', 'true')
      expect(await text.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe('pre-wrap')
      await toggle.click()
      await expect(text).not.toHaveClass(/cmd-text--expanded/)
    }
  })
})
