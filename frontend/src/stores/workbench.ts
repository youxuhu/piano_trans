import { defineStore } from 'pinia'
import type { HealthStatus, ScoreSummary, TranscriptionTask } from '../services/transcribe.ts'

const TASK_STORAGE_KEY = 'lingpu.taskId'
const VIEW_STORAGE_KEY = 'lingpu.viewMode'
const allowedTransitions: Record<TranscriptionTask['status'], TranscriptionTask['status'][]> = {
  queued: ['queued', 'running', 'completed', 'failed'],
  running: ['running', 'completed', 'failed'],
  completed: ['completed'],
  failed: ['failed'],
}

export const useWorkbenchStore = defineStore('workbench', {
  state: () => ({
    bpm: null as number | null,
    timeSignature: '4/4',
    quantization: 16,
    task: null as TranscriptionTask | null,
    taskId: localStorage.getItem(TASK_STORAGE_KEY) || '',
    retryFile: null as File | null,
    score: null as (Partial<ScoreSummary> & { title: string; duration?: number }) | null,
    scores: [] as ScoreSummary[],
    health: null as HealthStatus | null,
    error: '',
    viewMode: (localStorage.getItem(VIEW_STORAGE_KEY) === 'reader' ? 'reader' : 'import') as
      | 'import'
      | 'reader',
    libraryCollapsed: localStorage.getItem('lingpu.libraryCollapsed') === 'true',
  }),
  actions: {
    rememberTask(id: string, file: File) {
      this.taskId = id
      this.retryFile = file
      localStorage.setItem(TASK_STORAGE_KEY, id)
    },
    startTask(task: TranscriptionTask) {
      this.task = task
    },
    updateTask(next: TranscriptionTask) {
      if (this.task && !allowedTransitions[this.task.status].includes(next.status)) return false
      this.task = next
      return true
    },
    clearTask() {
      this.taskId = ''
      localStorage.removeItem(TASK_STORAGE_KEY)
    },
    clearScore() {
      this.score = null
    },
    setViewMode(mode: 'import' | 'reader') {
      this.viewMode = mode
      localStorage.setItem(VIEW_STORAGE_KEY, mode)
    },
  },
})
