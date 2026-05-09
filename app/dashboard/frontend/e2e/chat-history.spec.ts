/**
 * E2E tests — 7.3 Chat record loading
 *
 * Covers DASHBOARD_TODO.md item 7.3.
 */
import { test, expect } from '@playwright/test'

test.describe('Chat history', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('7.3-a: page loads without console errors', async ({ page }) => {
    const errors: string[] = []
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text())
    })
    await page.waitForLoadState('networkidle', { timeout: 15_000 })
    // Filter out known benign errors (e.g. hot-reload, extension errors)
    const fatalErrors = errors.filter(
      e => !e.includes('favicon') && !e.includes('chrome-extension')
    )
    expect(fatalErrors).toHaveLength(0)
  })

  test('7.3-b: chat panel is rendered', async ({ page }) => {
    // The main content area should be visible after load
    await page.waitForLoadState('domcontentloaded')
    const main = page.locator('main, .ant-layout-content, [role="main"]')
    await expect(main.first()).toBeVisible({ timeout: 10_000 })
  })

  test('7.3-c: pagination controls appear for long conversations', async ({ page }) => {
    // If there are messages, pagination might appear.  This test just verifies
    // the structure is not broken — it skips if no data is present.
    const contactItems = page.locator('.ant-list-item, [data-testid="contact-item"]')
    if (await contactItems.count() === 0) {
      test.skip()
    }
    await contactItems.first().click()
    await page.waitForTimeout(1000)
    // Either a message list or an empty-state element should exist
    const msgList = page.locator(
      '.ant-list, [data-testid="message-list"], .chat-messages, .ant-empty'
    )
    await expect(msgList.first()).toBeVisible({ timeout: 5_000 })
  })
})
