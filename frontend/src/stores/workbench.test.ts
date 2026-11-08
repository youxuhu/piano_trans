import test from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkbenchStore } from './workbench.ts'

function installStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial))
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    },
  })
  return values
}

test('restores a persisted task id and follows queued to running to completed', () => {
  const storage = installStorage({ 'lingpu.taskId': 'persisted-22' })
  setActivePinia(createPinia())
  const store = useWorkbenchStore()
  assert.equal(store.taskId, 'persisted-22')
  store.updateTask({ id: 'persisted-22', status: 'queued' })
  assert.equal(store.updateTask({ id: 'persisted-22', status: 'running' }), true)
  assert.equal(
    store.updateTask({ id: 'persisted-22', status: 'completed', score_id: 'score-3' }),
    true,
  )
  store.clearTask()
  assert.equal(store.taskId, '')
  assert.equal(storage.has('lingpu.taskId'), false)
})

test('rejects invalid task state regression but allows retry to start a fresh task', () => {
  installStorage()
  setActivePinia(createPinia())
  const store = useWorkbenchStore()
  store.startTask({ id: 'failed-task', status: 'failed' })
  assert.equal(store.updateTask({ id: 'failed-task', status: 'running' }), false)
  store.startTask({ id: 'retry-task', status: 'queued' })
  assert.equal(store.updateTask({ id: 'retry-task', status: 'running' }), true)
})
