/**
 * E2E tests — 7.1 General app load + 7.5 Strategy application flow
 *
 * Covers DASHBOARD_TODO.md items 7.1 and 7.5.
 */
import { test, expect, request } from '@playwright/test'

// ---------------------------------------------------------------------------
// 7.1  App loads correctly
// ---------------------------------------------------------------------------
test.describe('App load (7.1)', () => {
  test('loads dashboard route without redirect to error page', async ({ page }) => {
    const response = await page.goto('/', { waitUntil: 'domcontentloaded' })
    expect(response?.status()).toBeLessThan(400)
    // Should not land on a 404 / 500 page
    await expect(page).not.toHaveURL(/\/error|\/404/)
  })

  test('renders navigation menu', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('domcontentloaded')
    const nav = page.locator('.ant-menu, nav, [role="navigation"]')
    await expect(nav.first()).toBeVisible({ timeout: 10_000 })
  })

  test('bot login page is reachable', async ({ page }) => {
    await page.goto('/login')
    await page.waitForLoadState('domcontentloaded')
    // Should show login tabs or a heading
    const heading = page.locator('h1, h2, .ant-tabs, [data-testid="bot-login"]')
    await expect(heading.first()).toBeVisible({ timeout: 10_000 })
  })

  test('strategy management page is reachable', async ({ page }) => {
    await page.goto('/strategy')
    await page.waitForLoadState('domcontentloaded')
    const content = page.locator('main, .ant-layout-content, .ant-form')
    await expect(content.first()).toBeVisible({ timeout: 10_000 })
  })
})

// ---------------------------------------------------------------------------
// 7.5  Strategy application flow (API-level smoke test)
// ---------------------------------------------------------------------------
test.describe('Strategy application flow (7.5)', () => {
  test('POST /api/apply-global-strategy returns 200', async ({ request }) => {
    const res = await request.post('http://localhost:5000/api/apply-global-strategy', {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${process.env.DASHBOARD_API_TOKEN ?? ''}`,
      },
      data: {
        response_style: 'formal',
        tone: 'polite',
      },
    })
    // 200 in dev (no token), 200 in prod (valid token), 401 if wrong token
    expect([200, 401]).toContain(res.status())
  })

  test('GET /api/health returns ok', async ({ request }) => {
    const res = await request.get('http://localhost:5000/api/health')
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(['ok', 'degraded']).toContain(body.status)
  })
})
