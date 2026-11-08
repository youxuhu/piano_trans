import test from 'node:test'
import assert from 'node:assert/strict'
import { createPlaybackRange } from './playbackRange.ts'

test('A/B range requires finite ticks and B strictly after A', () => {
  assert.deepEqual(createPlaybackRange(120, 960), { startTick: 120, endTick: 960 })
  assert.equal(createPlaybackRange(120, 120), null)
  assert.equal(createPlaybackRange(500, 100), null)
  assert.equal(createPlaybackRange(-1, 100), null)
  assert.equal(createPlaybackRange(0, Number.NaN), null)
})
