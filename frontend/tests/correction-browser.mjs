// Controlled API fixtures exercise the editor without changing a user library or loading a GPU.
import { chromium } from 'playwright'
import fs from 'node:fs'
import assert from 'node:assert/strict'
const xml = fs.readFileSync(new URL('../public/real_piano.musicxml', import.meta.url))
const initial = [
  { id: 'held', pitch: 48, start: 0, end: 3, velocity: 80, hand: null },
  { id: 'edit', pitch: 60, start: 1, end: 1.5, velocity: 90, hand: null },
  { id: 'after', pitch: 72, start: 3, end: 4, velocity: 90, hand: null },
]
const options = { bpm: 120, time_signature: '4/4', quantization: 16, hand_split: 64, key_fifths: 0 }
let revision = 0,
  position = 0,
  versions = [structuredClone(initial)],
  taskNumber = 0,
  tasks = new Map()
const session = () => ({
  notes: structuredClone(versions[position]),
  pedals: [],
  revision,
  can_undo: position > 0,
  can_redo: position < versions.length - 1,
  duration: 5,
  options,
})
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] })
const context = await browser.newContext({ viewport: { width: 1864, height: 884 } }),
  page = await context.newPage(),
  errors = []
page.on('pageerror', (e) => errors.push(e.message))
await context.route('**/api/**', async (route) => {
  const path = new URL(route.request().url()).pathname,
    method = route.request().method()
  const item = {
    id: 'score',
    title: '纠错验收',
    bpm: 120,
    duration: 5,
    has_audio: false,
    can_regenerate: true,
    note_count: versions[position].length,
    revision,
  }
  if (path === '/api/health')
    return route.fulfill({
      json: { status: 'ok', ready: true, worker_alive: true, model_loaded: true },
    })
  if (path === '/api/scores') return route.fulfill({ json: [item] })
  if (path === '/api/scores/score') return route.fulfill({ json: item })
  if (path === '/api/scores/score/artifacts/musicxml')
    return route.fulfill({ contentType: 'application/xml', body: xml })
  if (path === '/api/scores/score/events' && method === 'GET')
    return route.fulfill({ json: session() })
  const body = method === 'POST' || method === 'PUT' ? route.request().postDataJSON() : null
  if (path === '/api/scores/score/events' && method === 'PUT') {
    if (body.expected_revision !== revision)
      return route.fulfill({ status: 409, json: { detail: '曲目已更新，请重新载入' } })
    versions = versions.slice(0, position + 1)
    versions.push(structuredClone(body.notes))
    position++
    revision++
    return route.fulfill({ json: session() })
  }
  if (path.includes('/history/')) {
    position += path.endsWith('/undo') ? -1 : 1
    revision++
    return route.fulfill({ json: session() })
  }
  if (path === '/api/scores/score/retranscriptions') {
    const id = 'partial-' + ++taskNumber
    tasks.set(id, {
      ...body,
      id,
      base_revision: revision,
      polls: 0,
      notes: [
        { id: 'new-' + taskNumber, pitch: 65, start: 1.1, end: 1.6, velocity: 80, hand: null },
      ],
      pedals: [],
      old_note_count: 1,
    })
    return route.fulfill({ status: 202, json: { task_id: id } })
  }
  if (path.startsWith('/api/tasks/')) {
    const task = tasks.get(path.split('/').at(-1))
    task.polls++
    return route.fulfill({
      json: {
        id: task.id,
        status: task.polls >= 2 ? 'completed' : 'running',
        stage: task.polls >= 2 ? 'review' : 'transcribing',
        progress: task.polls >= 2 ? 100 : 50,
      },
    })
  }
  const match = path.match(/\/retranscriptions\/([^/]+)(\/apply)?$/)
  if (match) {
    const result = tasks.get(match[1])
    if (!match[2]) return route.fulfill({ json: result })
    if (body.expected_revision !== revision || result.base_revision !== revision)
      return route.fulfill({ status: 409, json: { detail: '曲目已更新，请重新载入' } })
    const notes = versions[position]
      .filter((n) => n.start < result.start || n.start >= result.end)
      .concat(result.notes)
    versions = versions.slice(0, position + 1)
    versions.push(notes)
    position++
    revision++
    return route.fulfill({ json: session() })
  }
  return route.fulfill({ status: 404, json: { detail: '测试记录不存在' } })
})
const waitSaved = async (trigger) => {
  const response = page.waitForResponse(
    (r) => r.url().includes('/events') && r.request().method() === 'PUT' && r.status() === 200,
  )
  await trigger()
  await response
  await page.waitForTimeout(300)
  await page.locator('.score-loading').waitFor({ state: 'hidden' })
}
const waitHistory = async (trigger) => {
  const response = page.waitForResponse((r) => r.url().includes('/history/') && r.status() === 200)
  await trigger()
  await response
  await page.waitForTimeout(300)
  await page.locator('.score-loading').waitFor({ state: 'hidden' })
}
try {
  await page.goto(process.env.LINGPU_TEST_URL || 'http://127.0.0.1:5176')
  await page.locator('.score-entry').first().click()
  await page.locator('.score-loading').waitFor({ state: 'hidden' })
  await page.getByRole('button', { name: '纠错', exact: true }).click()
  await page.locator('.piano-roll').waitFor()
  const graph = await page.locator('.piano-roll').boundingBox()
  assert.ok(graph.width > 700, `Graph should use workspace width: ${graph.width}`)
  assert.equal(await page.locator('.sidebar').isVisible(), false)
  const note = page.getByRole('button', { name: 'C4，1.00 秒', exact: true })
  const rect = await note.boundingBox()
  await page.mouse.move(rect.x + rect.width / 2, rect.y + 7)
  await page.mouse.down()
  await page.mouse.move(rect.x + rect.width / 2 + graph.width / 12, rect.y - 11, { steps: 8 })
  await page.mouse.up()
  assert.equal(await page.locator('.note-fields input').first().inputValue(), '61')
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await page.screenshot({ path: '../docs/correction-fullscreen.png' })
  console.log('PASS full-width workspace and pointer note movement')
  await page.locator('.event-details summary').click()
  await page.locator('.event-list button').filter({ hasText: 'C4' }).click()
  await page.locator('.note-fields input').first().fill('62')
  await page.locator('.note-fields input').first().press('Tab')
  await page.locator('.note-fields .n-base-selection').click()
  await page.locator('.n-base-select-option').filter({ hasText: '左手' }).click()
  await waitSaved(() => page.getByRole('button', { name: '保存并更新谱面' }).click())
  assert.equal(versions[position].find((n) => n.id === 'edit').pitch, 62)
  assert.equal(versions[position].find((n) => n.id === 'edit').hand, 'left')
  await waitHistory(() => page.getByRole('button', { name: '撤销', exact: true }).click())
  assert.deepEqual(versions[position], initial)
  await waitHistory(() => page.getByRole('button', { name: '重做', exact: true }).click())
  console.log('PASS note correction, hand assignment and persistent undo/redo')
  await page.getByRole('button', { name: '添加音符', exact: true }).click()
  await page.getByRole('button', { name: '关闭纠错', exact: true }).click()
  await page.getByRole('button', { name: '继续编辑', exact: true }).click()
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  assert.equal(await page.locator('.note-editor').isVisible(), true)
  console.log('PASS unsaved navigation protection')
  await page.getByRole('button', { name: '局部重转录', exact: true }).click()
  await page.getByLabel('片段开始时间').locator('input').fill('1')
  await page.getByLabel('片段开始时间').locator('input').press('Tab')
  await page.getByLabel('片段结束时间').locator('input').fill('2')
  await page.getByLabel('片段结束时间').locator('input').press('Tab')
  const before = structuredClone(versions[position])
  await page.getByRole('button', { name: '重新识别片段', exact: true }).click()
  await page.locator('.partial-status').waitFor()
  await page.reload()
  await page.getByRole('button', { name: '纠错', exact: true }).click()
  await page.locator('.result-summary').waitFor({ timeout: 15000 })
  assert.deepEqual(versions[position], before)
  console.log('PASS region task restores after reload and waits for approval')
  const applied = page.waitForResponse((r) => r.url().endsWith('/apply'))
  await page.getByRole('button', { name: '应用替换结果', exact: true }).click()
  assert.equal((await applied).status(), 200)
  await page.waitForTimeout(500)
  assert.deepEqual(
    versions[position].filter((n) => n.start < 1 || n.start >= 2),
    before.filter((n) => n.start < 1 || n.start >= 2),
  )
  await page.getByRole('button', { name: '音符纠错', exact: true }).click()
  await waitHistory(() => page.getByRole('button', { name: '撤销', exact: true }).click())
  assert.deepEqual(versions[position], before)
  console.log('PASS only selected region replaced, with undo')
  assert.deepEqual(errors, [])
  console.log('PASS no browser exceptions')
} finally {
  await browser.close()
}
