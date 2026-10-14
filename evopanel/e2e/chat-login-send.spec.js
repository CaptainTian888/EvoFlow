import { test, expect } from '@playwright/test'

const baseURL = process.env.EVOFLOW_E2E_BASE_URL || 'http://127.0.0.1:1421'
const username = process.env.EVOFLOW_E2E_USERNAME || ''
const password = process.env.EVOFLOW_E2E_PASSWORD || ''
const message = process.env.EVOFLOW_E2E_MESSAGE || ''

test('explicitly requested: login, send one message in a new chat, and verify response', async ({ page }) => {
  test.skip(!message.trim(), 'Set EVOFLOW_E2E_MESSAGE and explicitly authorize sending a test message')
  test.skip(!password, 'Set EVOFLOW_E2E_PASSWORD in the process environment')

  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('console', (entry) => {
    if (entry.type() === 'error' && /fastdom_stub_default\.extend is not a function/.test(entry.text())) {
      pageErrors.push(entry.text())
    }
  })

  await page.goto(new URL('/#/chat', baseURL).href, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => {
    const splash = document.getElementById('boot-splash')
    return !splash || splash.classList.contains('boot-splash--hide')
  }, { timeout: 90_000 }).catch(() => {})

  const usernameInput = page.locator('#login-username')
  if (await usernameInput.isVisible().catch(() => false)) {
    await usernameInput.fill(username || 'admin')
    await page.locator('#login-password').fill(password)
    await page.locator('#login-submit').click()
    await expect(page).toHaveURL(/#\/chat(?:$|\?)/, { timeout: 30_000 })
  }

  const backendDown = page.locator('#backend-down-overlay')
  await expect(backendDown).toBeHidden({ timeout: 10_000 })

  const composer = page.getByRole('textbox', { name: '输入消息，@ 提及员工，# 引用文件' })
  await expect(composer).toBeVisible({ timeout: 90_000 })
  await expect(composer).toBeEnabled({ timeout: 90_000 })

  const newChat = page.getByRole('button', { name: /新建对话/ }).first()
  await newChat.click()
  await expect(composer).toBeEmpty()

  const userTurn = page.locator('.msg-user').filter({ hasText: message }).last()
  const send = page.getByRole('button', { name: '发送（Enter）' })
  await composer.fill(message)
  await send.click()
  await expect(userTurn).toBeVisible({ timeout: 30_000 })

  const assistantTurns = page.locator('.msg-turn--assistant:not(.msg-ai-streaming)')
  await expect.poll(async () => {
    const count = await assistantTurns.count()
    if (!count) return false
    const text = (await assistantTurns.last().innerText().catch(() => '')).trim()
    return Boolean(text)
  }, { timeout: 180_000, message: 'Expected a completed assistant response after sending the test message' }).toBe(true)

  expect(pageErrors.filter((error) => /fastdom_stub_default\.extend is not a function/.test(error))).toEqual([])
  expect(pageErrors, `Unexpected browser page errors: ${pageErrors.join('\n')}`).toEqual([])
})
