// The tool dialog remembers what you last entered (#80), but the group widgets
// are pre-filled from config.json rather than typed. A remembered value that
// outranks the config makes editing parent_group / gitlab_namespace look like
// it did nothing: the dialog keeps showing — and running against — the group
// the config named some edits ago.
//
// So a stored group value only survives while the config-derived default it was
// entered against is unchanged. Change the config and the config wins; leave it
// alone and a deliberate override still persists.
import { test, expect } from '@playwright/test'
import { mockApi, seedAuthedSession, TOOLS } from './support.js'

const CONFIG_DEFAULT = 'ns-current/GROUP-CURRENT'

// The shared fixture has no group-widget tool, so serve a variant of the ROAM
// tool carrying one. Registered after mockApi, so this handler wins.
async function mockToolsWithGroupParam(page) {
  const tools = TOOLS.map(t => t.key !== 'populate-roam' ? t : {
    ...t,
    params: [
      { name: 'target_group', prompt: 'Target group', type: 'str',
        widget: 'group', optional: true, default: CONFIG_DEFAULT },
      ...t.params,
    ],
  })
  await page.route('**/api/tools', route => route.fulfill({ json: tools }))
}

async function seedRemembered(page, { value, defaultWhenStored }) {
  await page.addInitScript(([v, d]) => {
    localStorage.setItem('nce-tool-params:populate-roam',
                         JSON.stringify({ target_group: v, count: 3 }))
    if (d !== null) {
      localStorage.setItem('nce-tool-params:populate-roam:defaults',
                           JSON.stringify({ target_group: d }))
    }
  }, [value, defaultWhenStored ?? null])
}

async function openRoamDialog(page) {
  await page.goto('/app/')
  await expect(page.locator('.nav-bar')).toBeVisible()
  await page.getByRole('button', { name: /ROAM Risk/ }).click()
  await page.getByText('Populate ROAM', { exact: true }).click()
  const dialog = page.locator('.overlay .dialog')
  await expect(dialog).toBeVisible()
  return dialog.locator('.group-field .ps-input')
}

test.describe('group param follows config.json', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuthedSession(page)
    await mockApi(page)
    await mockToolsWithGroupParam(page)
  })

  test('a value stored against an older config is replaced by the new one', async ({ page }) => {
    await seedRemembered(page, {
      value: 'ns-old/GROUP-OLD',
      defaultWhenStored: 'ns-old/GROUP-OLD',
    })
    await expect(await openRoamDialog(page)).toHaveValue(CONFIG_DEFAULT)
  })

  test('an override entered against the current config still persists', async ({ page }) => {
    await seedRemembered(page, {
      value: 'ns-current/SOMEWHERE-ELSE',
      defaultWhenStored: CONFIG_DEFAULT,
    })
    await expect(await openRoamDialog(page)).toHaveValue('ns-current/SOMEWHERE-ELSE')
  })

  test('a value stored before defaults were tracked falls back to config', async ({ page }) => {
    // Upgrade path: entries written by the old build carry no defaults key, and
    // those are exactly the stale ones this fixes.
    await seedRemembered(page, { value: 'ns-old/GROUP-OLD', defaultWhenStored: null })
    await expect(await openRoamDialog(page)).toHaveValue(CONFIG_DEFAULT)
  })

  test('non-group params keep being remembered', async ({ page }) => {
    await seedRemembered(page, { value: 'ns-old/GROUP-OLD', defaultWhenStored: null })
    const dialog = page.locator('.overlay .dialog')
    await openRoamDialog(page)
    await expect(dialog.locator('input[type="number"]').first()).toHaveValue('3')
  })
})
