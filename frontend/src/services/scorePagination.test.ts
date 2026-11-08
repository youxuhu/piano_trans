import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeScoreDisplayTitle, paginateScoreSystems } from './scorePagination.ts'

test('packs complete systems and never splits an over-height system', () => {
  const pages = paginateScoreSystems(
    [{ top: 0, bottom: 80 }, { top: 100, bottom: 180 }, { top: 200, bottom: 360 }],
    200,
  )
  assert.deepEqual(pages, [
    { firstSystem: 0, endSystem: 2, top: 0, bottom: 180 },
    { firstSystem: 2, endSystem: 3, top: 200, bottom: 360 },
  ])
})

test('handles empty and short scores', () => {
  assert.deepEqual(paginateScoreSystems([], 400), [])
  assert.deepEqual(paginateScoreSystems([{ top: 12, bottom: 32 }], 400), [
    { firstSystem: 0, endSystem: 1, top: 12, bottom: 32 },
  ])
})

test('reserves less space on the title page while later pages use the full height', () => {
  const pages = paginateScoreSystems(
    [{ top: 0, bottom: 60 }, { top: 60, bottom: 120 }, { top: 120, bottom: 210 }],
    150,
    100,
  )
  assert.deepEqual(pages, [
    { firstSystem: 0, endSystem: 1, top: 0, bottom: 60 },
    { firstSystem: 1, endSystem: 3, top: 60, bottom: 210 },
  ])
})

test('normalizes display labels and suppresses duplicate subtitles', () => {
  assert.deepEqual(normalizeScoreDisplayTitle('Prelude_in_C', 'Prelude_in_C'), {
    title: 'Prelude in C', subtitle: '',
  })
  assert.deepEqual(normalizeScoreDisplayTitle('Main_Title', 'Movement_One'), {
    title: 'Main Title', subtitle: 'Movement One',
  })
})
