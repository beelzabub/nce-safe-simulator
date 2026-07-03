import { defineConfig, devices } from '@playwright/test'

// Mobile-usability suite (issue #160). Every project runs the same specs
// against a real device profile: viewport, device-pixel ratio, touch, mobile
// user agent. The specs themselves branch on the phone/tablet breakpoint.
//
// Apple device descriptors default to WebKit — the actual Safari engine.
// WebKit needs system libraries that not every host has (install with
// `sudo npx playwright install-deps webkit`), so the default matrix forces
// Chromium (emulating each device's metrics) and the true-Safari projects
// are opt-in via PW_WEBKIT=1 / `npm run test:mobile:webkit`.
const onChromium = (name) => ({ ...devices[name], browserName: 'chromium' })

const projects = [
  { name: 'iphone-se',           use: onChromium('iPhone SE') },            // 320×568 — smallest supported phone
  { name: 'iphone-14',           use: onChromium('iPhone 14') },            // 390×664
  { name: 'iphone-14-landscape', use: onChromium('iPhone 14 landscape') },  // 750×340 — short-viewport case
  { name: 'pixel-7',             use: devices['Pixel 7'] },                 // 412×839, Android Chrome
  { name: 'galaxy-s9-plus',      use: devices['Galaxy S9+'] },              // 320×658, Android Chrome
  { name: 'ipad-gen7',           use: onChromium('iPad (gen 7)') },         // 810×1080 — tablet keeps desktop layout
]

if (process.env.PW_WEBKIT) {
  projects.push(
    { name: 'iphone-14-safari', use: devices['iPhone 14'] },
    { name: 'ipad-safari',      use: devices['iPad (gen 7)'] },
  )
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5199',
    trace: 'retain-on-failure',
  },
  projects,
  webServer: {
    command: 'npm run dev -- --port 5199 --strictPort',
    url: 'http://localhost:5199/app/',
    reuseExistingServer: !process.env.CI,
  },
})
