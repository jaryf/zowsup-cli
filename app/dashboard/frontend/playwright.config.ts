import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright configuration for Dashboard E2E tests.
 *
 * Tests require both services to be running:
 *   - Flask API: python script/dashboard.py  (port 5000)
 *   - Vite dev: npm run dev               (port 5173)
 *
 * Or you can use `npm run build` + Flask serving static/ in production mode.
 *
 * Run: npx playwright test
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,  // Tests share a live backend — run sequentially
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [['html', { open: 'never' }], ['list']],

  use: {
    // Base URL for the Vite dev server (proxies /api to Flask)
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // Bearer token passed as query param (DASHBOARD_API_TOKEN in Flask env)
    extraHTTPHeaders: {
      Authorization: `Bearer ${process.env.DASHBOARD_API_TOKEN ?? ''}`,
    },
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Automatically start both services before tests — comment out if you
  // prefer to start them manually.
  // webServer: [
  //   {
  //     command: 'npm run dev',
  //     url: 'http://localhost:5173',
  //     reuseExistingServer: !process.env.CI,
  //   },
  //   {
  //     command: 'python ../../../script/dashboard.py',
  //     url: 'http://localhost:5000/api/health',
  //     reuseExistingServer: !process.env.CI,
  //     cwd: '..',
  //   },
  // ],
})
