import test from 'node:test'
import assert from 'node:assert/strict'
import {
  artifactUrl,
  deleteScore,
  getScore,
  getTask,
  renameScore,
  transcribe,
} from './transcribe.ts'

const restoreFetch = () => {
  const original = globalThis.fetch
  return () => {
    globalThis.fetch = original
  }
}

test('transcribe sends the exact multipart payload and returns task id', async () => {
  const restore = restoreFetch()
  let captured: { url: string; init?: RequestInit } | undefined
  globalThis.fetch = async (input, init) => {
    captured = { url: String(input), init }
    return new Response(JSON.stringify({ task_id: 'job-17' }), { status: 200 })
  }
  try {
    const file = new File(['audio'], 'piano.wav', { type: 'audio/wav' })
    assert.deepEqual(await transcribe(file, { bpm: 92, time_signature: '3/4', quantization: 8 }), {
      task_id: 'job-17',
    })
    assert.equal(captured?.url, '/api/transcriptions')
    assert.equal(captured?.init?.method, 'POST')
    const form = captured?.init?.body as FormData
    assert.equal(form.get('audio') instanceof File, true)
    assert.equal((form.get('audio') as File).name, 'piano.wav')
    assert.equal(form.get('bpm'), '92')
    assert.equal(form.get('time_signature'), '3/4')
    assert.equal(form.get('quantization'), '8')
  } finally {
    restore()
  }
})

test('transcribe omits unset bpm but submits defaults', async () => {
  const restore = restoreFetch()
  globalThis.fetch = async (_input, init) => {
    const form = init?.body as FormData
    assert.equal(form.has('bpm'), false)
    assert.equal(form.get('time_signature'), '4/4')
    assert.equal(form.get('quantization'), '16')
    return new Response(JSON.stringify({ task_id: 'job-18' }), { status: 200 })
  }
  try {
    await transcribe(new File(['x'], 'x.wav', { type: 'audio/wav' }))
  } finally {
    restore()
  }
})

test('score and task service methods encode ids and report backend errors', async () => {
  const restore = restoreFetch()
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init })
    if (String(input).includes('tasks'))
      return new Response(JSON.stringify({ id: 'a/b', status: 'running' }), { status: 200 })
    if (init?.method === 'PATCH')
      return new Response(JSON.stringify({ id: 'a/b', title: 'renamed' }), { status: 200 })
    if (init?.method === 'DELETE') return new Response(null, { status: 204 })
    return new Response(JSON.stringify({ detail: 'missing score' }), { status: 404 })
  }
  try {
    assert.equal((await getTask('a/b')).status, 'running')
    assert.equal(calls[0].url, '/api/tasks/a%2Fb')
    assert.equal((await renameScore('a/b', 'renamed')).title, 'renamed')
    assert.deepEqual(JSON.parse(String(calls[1].init?.body)), { title: 'renamed' })
    await deleteScore('a/b')
    await assert.rejects(getScore('a/b'), /missing score/)
    assert.equal(artifactUrl('a/b', 'musicxml'), '/api/scores/a%2Fb/artifacts/musicxml')
  } finally {
    restore()
  }
})

test('service surfaces non-JSON HTTP errors without hiding status', async () => {
  const restore = restoreFetch()
  globalThis.fetch = async () => new Response('unavailable', { status: 503 })
  try {
    await assert.rejects(getTask('x'), /请求失败 \(503\)/)
  } finally {
    restore()
  }
})

test('transcribe exposes backend validation details', async () => {
  const restore = restoreFetch()
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: 'unsupported audio codec' }), { status: 422 })
  try {
    await assert.rejects(
      transcribe(new File(['x'], 'x.wav', { type: 'audio/wav' })),
      /unsupported audio codec/,
    )
  } finally {
    restore()
  }
})
