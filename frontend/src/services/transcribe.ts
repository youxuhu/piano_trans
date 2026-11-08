export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed'
export interface TranscriptionTask {
  id: string
  status: TaskStatus
  stage?: string
  elapsed_seconds?: number
  error?: string | null
  score_id?: string | null
  progress?: number | null
}
export interface ScoreSummary {
  id: string
  title: string
  created_at?: number
  duration?: number
  bpm?: number
  time_signature?: string
  note_count?: number
  has_audio?: boolean
  can_regenerate?: boolean
  revision?: number
  settings?: {
    quantization?: number
    hand_split?: number
    key_fifths?: number | null
    source?: string
  }
}
export interface HealthStatus {
  status: string
  device?: string
  model_loaded: boolean
  worker_alive: boolean
  ready: boolean
  error?: string | null
}
export interface TranscriptionOptions {
  bpm?: number | null
  time_signature?: string
  quantization?: number
}
export interface TaskSubmission {
  task_id: string
}
export type ArtifactType = 'audio' | 'midi' | 'musicxml'

const API = '/api'
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response
  const timeout = AbortSignal.timeout(30000)
  try {
    response = await fetch(`${API}${path}`, {
      ...options,
      signal: options?.signal ? AbortSignal.any([options.signal, timeout]) : timeout,
    })
  } catch (error) {
    if (error instanceof Error && error.name === 'TimeoutError')
      throw new ApiError('服务响应超时，请检查服务后重试', 408)
    throw error
  }
  if (!response.ok) {
    let message = `请求失败 (${response.status})`
    try {
      const data: { detail?: string | { msg: string }[]; error?: string } = await response.json()
      message = Array.isArray(data.detail)
        ? data.detail.map((d) => d.msg).join('；')
        : data.detail || data.error || message
    } catch {
      /* Non-JSON backend error */
    }
    throw new ApiError(message, response.status)
  }
  return (response.status === 204 ? null : response.json()) as Promise<T>
}

export const getHealth = (): Promise<HealthStatus> => request('/health')
export const getScores = (): Promise<ScoreSummary[]> => request('/scores')
export const getScore = (id: string, signal?: AbortSignal): Promise<ScoreSummary> =>
  request(`/scores/${encodeURIComponent(id)}`, { signal })
export const renameScore = (id: string, title: string): Promise<ScoreSummary> =>
  request(`/scores/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
export const deleteScore = (id: string): Promise<void> =>
  request(`/scores/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const artifactUrl = (id: string, type: ArtifactType): string =>
  `${API}/scores/${encodeURIComponent(id)}/artifacts/${type}`
export const getTask = (id: string): Promise<TranscriptionTask> =>
  request(`/tasks/${encodeURIComponent(id)}`)
export async function transcribe(
  file: File,
  options: TranscriptionOptions = {},
): Promise<TaskSubmission> {
  const form = new FormData()
  form.append('audio', file, file.name)
  if (options.bpm != null) form.append('bpm', String(options.bpm))
  form.append('time_signature', options.time_signature || '4/4')
  form.append('quantization', String(options.quantization ?? 16))
  return request('/transcriptions', { method: 'POST', body: form })
}

export async function importScore(file: File): Promise<ScoreSummary> {
  const form = new FormData()
  form.append('file', file, file.name)
  return request('/scores/import', { method: 'POST', body: form })
}
export interface ScoreOptions {
  bpm: number
  time_signature: string
  quantization: number
  hand_split: number
  key_fifths: number | null
}
export const regenerateScore = (id: string, options: ScoreOptions): Promise<ScoreSummary> =>
  request(`/scores/${encodeURIComponent(id)}/regenerate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  })

export interface EditorNote {
  id: string
  pitch: number
  start: number
  end: number
  velocity: number
  hand: 'right' | 'left' | null
}
export interface EventSession {
  notes: EditorNote[]
  pedals: { start: number; end: number }[]
  revision: number
  can_undo: boolean
  can_redo: boolean
  duration: number
  options: ScoreOptions
}
export interface PartialResult {
  notes: EditorNote[]
  pedals: { start: number; end: number }[]
  base_revision: number
  start: number
  end: number
  old_note_count: number
}
const scorePath = (id: string) => `/scores/${encodeURIComponent(id)}`
export const getEvents = (id: string): Promise<EventSession> => request(`${scorePath(id)}/events`)
export const saveNotes = (
  id: string,
  revision: number,
  notes: EditorNote[],
): Promise<EventSession> =>
  request(`${scorePath(id)}/events`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_revision: revision, notes }),
  })
export const moveEditHistory = (
  id: string,
  revision: number,
  action: 'undo' | 'redo',
): Promise<EventSession> =>
  request(`${scorePath(id)}/history/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_revision: revision }),
  })
export const retranscribeRegion = (
  id: string,
  revision: number,
  start: number,
  end: number,
): Promise<TaskSubmission> =>
  request(`${scorePath(id)}/retranscriptions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_revision: revision, start, end }),
  })
export const getPartialResult = (id: string, task: string): Promise<PartialResult> =>
  request(`${scorePath(id)}/retranscriptions/${encodeURIComponent(task)}`)
export const applyPartialResult = (
  id: string,
  task: string,
  revision: number,
): Promise<EventSession> =>
  request(`${scorePath(id)}/retranscriptions/${encodeURIComponent(task)}/apply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_revision: revision }),
  })
