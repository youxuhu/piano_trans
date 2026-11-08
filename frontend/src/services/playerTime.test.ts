import test from 'node:test'
import assert from 'node:assert/strict'
import { playerMillisecondsToScoreSeconds, scoreSecondsToPlayerMilliseconds } from './playerTime.ts'

test('converts wall time and duration to stable score time at playback speeds', () => {
  assert.equal(playerMillisecondsToScoreSeconds(900, 2), 1.8)
  assert.equal(playerMillisecondsToScoreSeconds(3600, 0.5), 1.8)
  assert.equal(playerMillisecondsToScoreSeconds(5000, 2), 10)
  assert.equal(playerMillisecondsToScoreSeconds(20000, 0.5), 10)
})

test('seek converts score time back to alphaTab wall-time coordinates', () => {
  assert.equal(scoreSecondsToPlayerMilliseconds(5, 2), 2500)
  assert.equal(scoreSecondsToPlayerMilliseconds(5, 0.5), 10000)
  for (const speed of [0.5, 0.75, 1, 1.25, 1.5, 2]) {
    const scoreSeconds = 7.25
    const alphaTabMs = scoreSecondsToPlayerMilliseconds(scoreSeconds, speed)
    assert.equal(playerMillisecondsToScoreSeconds(alphaTabMs, speed), scoreSeconds)
  }
})

test('invalid conversion inputs safely return zero', () => {
  assert.equal(playerMillisecondsToScoreSeconds(Number.NaN, 2), 0)
  assert.equal(playerMillisecondsToScoreSeconds(1200, 0), 0)
  assert.equal(scoreSecondsToPlayerMilliseconds(-5, 1), 0)
})
