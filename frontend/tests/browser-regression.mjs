// Run against a local Vite server. All API requests are intercepted; no user library is changed.
import { chromium } from 'playwright'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

const base = process.env.LINGPU_TEST_URL || 'http://127.0.0.1:5175'
const xml = fs.readFileSync(
  fileURLToPath(new URL('../public/real_piano.musicxml', import.meta.url)),
)
const audio = Buffer.alloc(44 + 16000 * 32 * 2)
audio.write('RIFF')
audio.writeUInt32LE(audio.length - 8, 4)
audio.write('WAVEfmt ', 8)
audio.writeUInt32LE(16, 16)
audio.writeUInt16LE(1, 20)
audio.writeUInt16LE(1, 22)
audio.writeUInt32LE(16000, 24)
audio.writeUInt32LE(32000, 28)
audio.writeUInt16LE(2, 32)
audio.writeUInt16LE(16, 34)
audio.write('data', 36)
audio.writeUInt32LE(audio.length - 44, 40)
const records = [
  {
    id: 'long',
    title: '长曲目',
    bpm: 120,
    duration: 32,
    note_count: 375,
    has_audio: true,
    can_regenerate: true,
  },
  {
    id: 'other',
    title: '另一首曲目',
    bpm: 120,
    duration: 32,
    note_count: 375,
    has_audio: true,
    can_regenerate: true,
  },
]
let delayed = false,
  completed = false
const browser = await chromium.launch({
  headless: true,
  args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'],
})
const context = await browser.newContext({ viewport: { width: 1864, height: 884 } })
const page = await context.newPage(),
  errors = []
page.on('pageerror', (e) => errors.push(e.message))
await context.route('**/api/**', async (route) => {
  const path = new URL(route.request().url()).pathname
  if (path === '/api/health')
    return route.fulfill({
      json: { ready: true, model_loaded: true, worker_alive: true, status: 'ok' },
    })
  if (path === '/api/scores') return route.fulfill({ json: records })
  if (path === '/api/tasks/job')
    return route.fulfill({
      json: {
        id: 'job',
        status: completed ? 'completed' : 'running',
        stage: completed ? 'completed' : 'transcribing',
        score_id: completed ? 'long' : null,
      },
    })
  if (path === '/api/scores/import') {
    const score = {
      id: 'imported',
      title: '导入验收',
      bpm: 120,
      duration: 32,
      has_audio: false,
      can_regenerate: false,
    }
    records.push(score)
    return route.fulfill({ status: 201, json: score })
  }
  const match = path.match(/^\/api\/scores\/([^/]+)(?:\/(artifacts|regenerate)(?:\/(\w+))?)?$/)
  const score = records.find((s) => s.id === match?.[1])
  if (!score) return route.fulfill({ status: 404, json: { detail: '记录不存在' } })
  if (match[2] === 'artifacts') {
    if (match[3] !== 'audio') return route.fulfill({ contentType: 'application/xml', body: xml })
    const range = route
      .request()
      .headers()
      .range?.match(/bytes=(\d+)-(\d*)/)
    if (range) {
      const start = +range[1],
        end = range[2] ? Math.min(+range[2], audio.length - 1) : audio.length - 1
      return route.fulfill({
        status: 206,
        headers: {
          'Content-Range': `bytes ${start}-${end}/${audio.length}`,
          'Accept-Ranges': 'bytes',
        },
        contentType: 'audio/wav',
        body: audio.subarray(start, end + 1),
      })
    }
    return route.fulfill({
      contentType: 'audio/wav',
      headers: { 'Accept-Ranges': 'bytes' },
      body: audio,
    })
  }
  if (match[2] === 'regenerate') {
    score.bpm = route.request().postDataJSON().bpm
    return route.fulfill({ json: score })
  }
  if (delayed) await new Promise((r) => setTimeout(r, score.id === 'long' ? 600 : 20))
  try {
    await route.fulfill({ json: score })
  } catch {
    /* an obsolete request was cancelled */
  }
})
const open = async (title) => {
  await page.locator('.score-entry').first().waitFor({ state: 'attached' })
  if (!(await page.locator('.score-entry').first().isVisible()))
    await page.getByRole('button', { name: '展开曲库' }).click()
  await page.locator('.score-entry').filter({ hasText: title }).click()
  await page.locator('.at-surface-svg').first().waitFor()
  await page.locator('.score-loading').waitFor({ state: 'hidden' })
}
try {
  await page.goto(base)
  await open('长曲目')
  await page.waitForTimeout(500)
  assert.equal(await page.locator('.source-option').nth(1).isDisabled(), false)
  await open('长曲目')
  assert.equal(await page.locator('.source-option').nth(1).isDisabled(), false)
  console.log('PASS repeated opening preserves original-audio availability')
  let box = await page.locator('.at-scroll-viewport').boundingBox()
  await page.mouse.click(box.x + box.width * 0.85, box.y + box.height * 0.4)
  const preferences = () =>
    page.evaluate(() => JSON.parse(localStorage.getItem('lingpu.reader.long')))
  const before = await preferences()
  await page.getByRole('button', { name: '收起节拍器' }).click()
  await page.waitForTimeout(600)
  assert.equal((await preferences()).bar, before.bar)
  await page.reload()
  await page.locator('.score-loading').waitFor({ state: 'hidden' })
  await page.locator('.at-surface-svg').first().waitFor()
  assert.equal((await preferences()).bar, before.bar)
  console.log('PASS layout changes and refresh retain musical reading anchor')
  delayed = true
  await page.locator('.score-entry').filter({ hasText: '长曲目' }).click()
  await page.locator('.score-entry').filter({ hasText: '另一首曲目' }).click()
  await page.waitForTimeout(1000)
  assert.equal(await page.locator('.paper-title').innerText(), '另一首曲目')
  delayed = false
  console.log('PASS latest score selection wins under delayed responses')
  await page.evaluate(() => localStorage.setItem('lingpu.taskId', 'job'))
  await page.reload()
  await page.locator('.score-loading').waitFor({ state: 'hidden' })
  await page.locator('.paper-title').waitFor()
  completed = true
  await page.getByText('新乐谱已准备好', { exact: false }).waitFor()
  assert.equal(await page.locator('.paper-title').innerText(), '另一首曲目')
  console.log('PASS background completion does not replace the reading score')
  await page.getByRole('button', { name: '练习', exact: true }).click()
  await page.locator('.practice-toggle').click()
  await page.locator('.tp-btn.main').click()
  await page.locator('.count-in').waitFor()
  await page.locator('.count-in').waitFor({ state: 'hidden', timeout: 10000 })
  await page.waitForTimeout(300)
  assert.equal(await page.locator('.tp-btn.main').getAttribute('title'), '暂停')
  await page.locator('.tp-btn.main').click()
  console.log('PASS one-bar count-in starts score playback')
  await page.getByRole('button', { name: '视图与设置' }).click()
  await page.getByText('专注看谱', { exact: true }).click()
  assert.equal(await page.locator('.sidebar').isVisible(), false)
  await page.getByRole('button', { name: '退出专注' }).click()
  await page.getByRole('button', { name: '导入', exact: true }).click()
  await page
    .locator('input[type=file]')
    .setInputFiles({ name: 'import.musicxml', mimeType: 'application/xml', buffer: xml })
  await page.getByText('乐谱已保存到曲库', { exact: true }).waitFor()
  await page.reload()
  await page.locator('.paper-title').waitFor()
  assert.equal(await page.locator('.paper-title').innerText(), '导入验收')
  assert.equal(await page.locator('.source-option').nth(1).isDisabled(), true)
  console.log('PASS imported score survives reload and has no original-audio control')
  await page.setViewportSize({ width: 768, height: 1024 })
  await page.waitForTimeout(700)
  assert.ok((await page.locator('.bottom-player').boundingBox()).height < 100)
  await page.locator('.extra-controls summary').click()
  assert.equal(await page.locator('.speed-wrap').isVisible(), true)
  console.log('PASS tablet keeps compact player and expandable controls')
  assert.deepEqual(errors, [])
  console.log('PASS no browser exceptions')
} finally {
  await browser.close()
}
