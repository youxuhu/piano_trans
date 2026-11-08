import test from 'node:test'
import assert from 'node:assert/strict'
import { findSelectedNote } from './noteEditing.ts'
import type { EditorNote } from './transcribe.ts'

const note = (
  id: string,
  start: number,
  end: number,
  hand: EditorNote['hand'] = null,
): EditorNote => ({ id, pitch: 60, start, end, hand, velocity: 90 })
test('matches a quantized note head to its original onset without choosing another chord pitch', () => {
  const original = note('c4', 0.118, 0.43)
  assert.equal(
    findSelectedNote(
      [{ ...original, id: 'e4', pitch: 64 }, original],
      { pitch: 60, time: 0.125, hand: 'right' },
      0.08,
    )?.id,
    'c4',
  )
})
test('selects tied long notes and distinguishes nearby repeated attacks', () => {
  const notes = [note('held', 0, 1.4), note('repeat', 1, 1.8)]
  assert.equal(findSelectedNote(notes, { pitch: 60, time: 0.75, hand: 'right' }, 0.08)?.id, 'held')
  assert.equal(findSelectedNote(notes, { pitch: 60, time: 1, hand: 'right' }, 0.08)?.id, 'repeat')
})
test('respects an explicitly assigned hand for simultaneous same-pitch events', () => {
  const notes = [note('left', 0, 1, 'left'), note('right', 0, 1, 'right')]
  assert.equal(findSelectedNote(notes, { pitch: 60, time: 0, hand: 'right' }, 0.08)?.id, 'right')
  assert.equal(findSelectedNote(notes, { pitch: 61, time: 0, hand: 'right' }, 0.08), undefined)
})
