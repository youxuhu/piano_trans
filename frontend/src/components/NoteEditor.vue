<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NAlert, NButton, NInputNumber, NSelect, NSlider } from 'naive-ui'
import {
  ApiError,
  artifactUrl,
  applyPartialResult,
  getEvents,
  getPartialResult,
  getTask,
  moveEditHistory,
  retranscribeRegion,
  saveNotes,
} from '../services/transcribe'
import type {
  EditorNote,
  EventSession,
  PartialResult,
  TranscriptionTask,
} from '../services/transcribe'
import { findSelectedNote, pitchLabel } from '../services/noteEditing'
import type { NoteSelection } from '../services/noteEditing'

const props = defineProps<{ scoreId: string; current: number; selection: NoteSelection | null; title?: string }>()
const emit = defineEmits<{
  saved: []
  'select-time': [time: number]
  close: []
  'listen-range': [range: { start: number; end: number }]
}>()
const session = ref<EventSession | null>(null),
  draft = ref<EditorNote[]>([]),
  selected = ref('')
const form = ref<EditorNote | null>(null),
  error = ref(''),
  working = ref(false),
  loading = ref(true)
const mode = ref<'notes' | 'partial'>('notes'),
  windowStart = ref(0)
const windowSize = ref(6), snap = ref(true)
const undoStack = ref<EditorNote[][]>([]),
  redoStack = ref<EditorNote[][]>([])
const rangeStart = ref(0),
  rangeEnd = ref(5),
  partialId = ref(''),
  task = ref<TranscriptionTask | null>(null),
  result = ref<PartialResult | null>(null)
let generation = 0,
  timer = 0,
  disposed = false
const clone = (notes: EditorNote[]) => notes.map((n) => ({ ...n }))
const formatTime = (value: number | null) =>
  value != null && Number.isFinite(value) ? value.toFixed(4) : ''
const selectedNote = computed(() => draft.value.find((n) => n.id === selected.value))
const formDirty = computed(
  () => !!form.value && JSON.stringify(form.value) !== JSON.stringify(selectedNote.value),
)
const dirty = computed(
  () =>
    formDirty.value || JSON.stringify(draft.value) !== JSON.stringify(session.value?.notes || []),
)
const running = computed(
  () =>
    !!partialId.value &&
    (!task.value || task.value.status === 'queued' || task.value.status === 'running'),
)
const visible = computed(() =>
  draft.value
    .filter((n) => n.start < windowStart.value + windowSize.value && n.end > windowStart.value)
    .sort((a, b) => a.start - b.start || b.pitch - a.pitch),
)
const pitches = computed(() => {
  const values = [...visible.value, ...(result.value?.notes || [])].map((n) => n.pitch)
  return { min: Math.min(48, ...values), max: Math.max(72, ...values) }
})
const waveform = ref<number[]>([]), waveformLoading = ref(false), waveformError = ref('')
let waveformAbort: AbortController | null = null
async function loadWaveform() {
  if (waveformLoading.value || waveform.value.length) return
  waveformLoading.value = true
  waveformError.value = ''
  const version = generation
  const controller = new AbortController()
  waveformAbort = controller
  let context: AudioContext | null = null
  try {
    const response = await fetch(artifactUrl(props.scoreId, 'audio'), { signal: controller.signal })
    if (!response.ok) throw new Error('原音读取失败，可继续通过时间范围选择片段')
    context = new AudioContext()
    const audio = await context.decodeAudioData(await response.arrayBuffer())
    const peaks = Array.from({ length: 1600 }, (_, i) => {
      let peak = 0
      const start = Math.floor(i * audio.length / 1600), end = Math.floor((i + 1) * audio.length / 1600)
      for (let channel = 0; channel < audio.numberOfChannels; channel++) {
        const data = audio.getChannelData(channel)
        for (let j = start; j < end; j += Math.max(1, Math.floor((end - start) / 100))) peak = Math.max(peak, Math.abs(data[j] || 0))
      }
      return peak
    })
    if (!disposed && version === generation) waveform.value = peaks
  } catch (e) { if (!disposed && version === generation) waveformError.value = e instanceof Error ? e.message : String(e) }
  finally { await context?.close(); if (version === generation) waveformLoading.value = false }
}
const rows = computed(() => Array.from({ length: pitches.value.max - pitches.value.min + 1 }, (_, i) => pitches.value.max - i))
const rollHeight = computed(() => rows.value.length * 18)
const gridTimes = computed(() => Array.from({ length: 13 }, (_, i) => windowStart.value + i * windowSize.value / 12))
const blackKey = (pitch: number) => [1, 3, 6, 8, 10].includes(pitch % 12)
function shiftWindow(direction: number) {
  windowStart.value = Math.max(0, Math.min(Math.max(0, (session.value?.duration || 6) - 0.1), windowStart.value + direction * windowSize.value))
}
function dragNote(event: PointerEvent, note: EditorNote, resize = false) {
  if (event.button !== 0 || working.value || mode.value !== 'notes') return
  event.preventDefault()
  select(note)
  if (!updateSelected()) return
  const svg = (event.currentTarget as SVGElement).ownerSVGElement!
  const bounds = svg.getBoundingClientRect()
  const initial = { ...draft.value.find(n => n.id === note.id)! }
  const x = event.clientX, y = event.clientY
  let moved = false
  const step = snap.value ? 60 / (session.value?.options.bpm || 120) / 4 : 0.001
  const move = (e: PointerEvent) => {
    if (!moved && Math.abs(e.clientX - x) + Math.abs(e.clientY - y) < 4) return
    if (!moved) { checkpoint(); moved = true }
    const delta = Math.round(((e.clientX - x) / bounds.width * windowSize.value) / step) * step
    const changed = { ...initial }
    if (resize) changed.end = Math.max(initial.start + 0.025, Math.min(3600, initial.end + delta))
    else {
      changed.start = Math.max(0, Math.min(3600 - (initial.end - initial.start), initial.start + delta))
      changed.end = changed.start + initial.end - initial.start
      changed.pitch = Math.max(21, Math.min(108, initial.pitch - Math.round((e.clientY - y) / 18)))
    }
    draft.value = draft.value.map(n => n.id === initial.id ? changed : n)
    form.value = { ...changed }
  }
  const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); window.removeEventListener('pointercancel', stop); stopDrag = () => {} }
  stopDrag()
  stopDrag = stop
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
}
function selectRange(event: PointerEvent) {
  if (mode.value !== 'partial' || running.value || result.value || event.button !== 0) return
  event.preventDefault()
  const bounds = (event.currentTarget as SVGElement).getBoundingClientRect()
  const isWave = (event.currentTarget as SVGElement).getAttribute('aria-label')?.startsWith('原音波形')
  const time = (x: number) => Math.max(0, Math.min(session.value?.duration || 0, (isWave ? 0 : windowStart.value) + (x - bounds.left) / bounds.width * (isWave ? session.value?.duration || 1 : windowSize.value)))
  const start = time(event.clientX)
  const move = (e: PointerEvent) => { const end = time(e.clientX); rangeStart.value = Number(Math.min(start, end).toFixed(3)); rangeEnd.value = Number(Math.max(start, end).toFixed(3)) }
  const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); window.removeEventListener('pointercancel', stop); stopDrag = () => {} }
  stopDrag(); stopDrag = stop
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
}
let stopDrag = () => {}
const stage = computed(
  () =>
    ({
      queued: '排队中',
      decoding: '读取原音',
      transcribing: '识别片段',
      review: '等待应用',
      failed: '识别失败',
    })[task.value?.stage || task.value?.status || ''] || '处理中',
)
const staleResult = computed(
  () => result.value && result.value.base_revision !== session.value?.revision,
)

function checkpoint() {
  undoStack.value.push(clone(draft.value))
  if (undoStack.value.length > 50) undoStack.value.shift()
  redoStack.value = []
}
function valid(note: EditorNote) {
  return (
    Number.isFinite(note.pitch) &&
    note.pitch >= 21 &&
    note.pitch <= 108 &&
    Number.isInteger(note.pitch) &&
    Number.isFinite(note.start) &&
    note.start >= 0 &&
    Number.isFinite(note.end) &&
    note.end > note.start &&
    note.end <= 3600
  )
}
function updateSelected() {
  if (!form.value || !formDirty.value) return true
  if (!valid(form.value)) {
    error.value = '请检查音高和时间：结束必须晚于开始'
    return false
  }
  const changed = { ...form.value }
  checkpoint()
  draft.value = draft.value.map((n) => (n.id === changed.id ? changed : n))
  error.value = ''
  return true
}
function select(note: EditorNote) {
  if (!updateSelected()) return
  const current = draft.value.find((n) => n.id === note.id) || note
  emit('select-time', current.start)
  selected.value = current.id
  form.value = { ...current }
  windowStart.value = Math.max(0, Math.floor(current.start / windowSize.value) * windowSize.value)
}
function add() {
  if (!updateSelected()) return
  checkpoint()
  const start = Math.max(0, props.current || windowStart.value)
  const note: EditorNote = {
    id: crypto.randomUUID(),
    pitch: 60,
    start,
    end: start + 0.5,
    velocity: 90,
    hand: null,
  }
  draft.value.push(note)
  selected.value = note.id
  form.value = { ...note }
  windowStart.value = Math.floor(start / 6) * 6
}
function remove() {
  if (!selected.value) return
  checkpoint()
  draft.value = draft.value.filter((n) => n.id !== selected.value)
  selected.value = ''
  form.value = null
}
function adopt(value: EventSession) {
  session.value = value
  draft.value = clone(value.notes)
  undoStack.value = []
  redoStack.value = []
  const note = draft.value.find((n) => n.id === selected.value)
  selected.value = note?.id || ''
  form.value = note ? { ...note } : null
}
async function load() {
  const version = ++generation,
    id = props.scoreId
  loading.value = true
  error.value = ''
  clearTimeout(timer)
  try {
    const value = await getEvents(id)
    if (version !== generation || disposed) return
    adopt(value)
    selectFromScore(props.selection)
    rangeEnd.value = Math.min(value.duration || 5, Math.max(0.1, rangeStart.value + 5))
    const stored = localStorage.getItem('lingpu.partial.' + id)
    if (stored) {
      partialId.value = stored
      mode.value = 'partial'
      void poll(version, id)
    }
  } catch (e) {
    if (version === generation) error.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (version === generation) loading.value = false
  }
}
async function save() {
  if (!session.value || working.value || !updateSelected()) return
  const version = generation,
    id = props.scoreId
  working.value = true
  error.value = ''
  try {
    const value = await saveNotes(id, session.value.revision, clone(draft.value))
    if (version !== generation || disposed) return
    adopt(value)
    emit('saved')
  } catch (e) {
    if (version === generation) error.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (version === generation) working.value = false
  }
}
async function history(action: 'undo' | 'redo') {
  if (!session.value || working.value) return
  if (formDirty.value && action === 'undo') {
    form.value = selectedNote.value ? { ...selectedNote.value } : null
    return
  }
  const source = action === 'undo' ? undoStack : redoStack,
    target = action === 'undo' ? redoStack : undoStack
  if (source.value.length) {
    target.value.push(clone(draft.value))
    draft.value = source.value.pop()!
    form.value = selectedNote.value ? { ...selectedNote.value } : null
    return
  }
  if (dirty.value) return
  working.value = true
  error.value = ''
  const version = generation
  try {
    const value = await moveEditHistory(props.scoreId, session.value.revision, action)
    if (version !== generation) return
    adopt(value)
    emit('saved')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    working.value = false
  }
}
function setDuration(beats: number) {
  if (form.value && session.value)
    form.value.end = Number(
      (form.value.start + (beats * 60) / session.value.options.bpm).toFixed(4),
    )
}
function updateHand(value: string) {
  if (form.value) form.value.hand = value === 'right' || value === 'left' ? value : null
}
function selectFromScore(selection: NoteSelection | null) {
  if (!selection || !session.value) return
  mode.value = 'notes'
  const tolerance =
    ((60 / session.value.options.bpm) * 4) / session.value.options.quantization / 2 + 0.04
  const note = findSelectedNote(draft.value, selection, tolerance)
  if (note) select(note)
  else error.value = '此处没有对应的原始音符，可从下方事件列表选择或新增'
}
async function beginPartial() {
  if (!session.value || running.value || working.value) return
  if (dirty.value) {
    error.value = '请先保存或撤销当前音符修改，再重新识别片段'
    return
  }
  if (
    !Number.isFinite(rangeStart.value) ||
    !Number.isFinite(rangeEnd.value) ||
    rangeStart.value < 0 ||
    rangeEnd.value - rangeStart.value < 0.1 ||
    rangeEnd.value > session.value.duration + 0.025
  ) {
    error.value = '请选择原录音内至少 0.1 秒的片段'
    return
  }
  working.value = true
  error.value = ''
  result.value = null
  const version = generation,
    id = props.scoreId
  try {
    const response = await retranscribeRegion(
      id,
      session.value.revision,
      rangeStart.value,
      rangeEnd.value,
    )
    if (version !== generation) return
    partialId.value = response.task_id
    localStorage.setItem('lingpu.partial.' + id, response.task_id)
    task.value = { id: response.task_id, status: 'queued', stage: 'queued' }
    void poll(version, id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    working.value = false
  }
}
async function poll(version: number, id: string) {
  clearTimeout(timer)
  if (disposed || version !== generation || !partialId.value) return
  try {
    const value = await getTask(partialId.value)
    if (version !== generation || disposed) return
    task.value = value
    if (value.status === 'completed') {
      const preview = await getPartialResult(id, partialId.value)
      if (version !== generation || disposed) return
      result.value = preview
      rangeStart.value = preview.start
      rangeEnd.value = preview.end
      return
    }
    if (value.status === 'failed') {
      error.value = value.error || '片段识别失败'
      return
    }
  } catch (e) {
    if (version === generation) {
      error.value = e instanceof Error ? e.message : String(e)
      if (e instanceof ApiError && e.status === 404) {
        task.value = { id: partialId.value, status: 'failed', stage: 'failed' }
        localStorage.removeItem('lingpu.partial.' + id)
        return
      }
    }
  }
  if (!disposed && version === generation)
    timer = window.setTimeout(() => void poll(version, id), 1600)
}
async function apply() {
  if (!session.value || !result.value || dirty.value || staleResult.value || working.value) return
  working.value = true
  error.value = ''
  const version = generation
  try {
    const value = await applyPartialResult(props.scoreId, partialId.value, session.value.revision)
    if (version !== generation) return
    adopt(value)
    discardPartial()
    emit('saved')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    working.value = false
  }
}
function discardPartial() {
  clearTimeout(timer)
  localStorage.removeItem('lingpu.partial.' + props.scoreId)
  partialId.value = ''
  task.value = null
  result.value = null
}
function markRange(which: 'start' | 'end') {
  if (which === 'start')
    rangeStart.value = Math.max(0, Math.min(props.current, session.value?.duration || 0))
  else rangeEnd.value = Math.max(0, Math.min(props.current, session.value?.duration || 0))
}
watch(
  () => props.scoreId,
  () => {
    waveformAbort?.abort()
    waveform.value = []
    waveformLoading.value = false
    selected.value = ''
    form.value = null
    partialId.value = ''
    task.value = null
    result.value = null
    void load()
  },
  { immediate: true },
)
watch(() => props.selection, selectFromScore)
onBeforeUnmount(() => {
  waveformAbort?.abort()
  stopDrag()
  disposed = true
  generation++
  clearTimeout(timer)
})
defineExpose({ hasChanges: () => dirty.value, isWorking: () => working.value })
</script>

<template>
  <aside class="note-editor" aria-label="音符纠错与局部重转录">
    <header class="correction-header">
      <button class="back-reader" aria-label="关闭纠错" @click="emit('close')">‹ 返回看谱</button>
      <strong class="editor-title">{{ title || '纠错工作台' }}</strong>
      <nav class="editor-tabs"><button :class="{ active: mode === 'notes' }" @click="mode = 'notes'">音符纠错</button><button :class="{ active: mode === 'partial' }" @click="mode = 'partial'">局部重转录</button></nav>
      <div class="editor-history">
        <n-button size="small" :disabled="!session || working || (!undoStack.length && !session.can_undo && !formDirty)" @click="history('undo')">撤销</n-button>
        <n-button size="small" :disabled="!session || working || (!redoStack.length && !session.can_redo)" @click="history('redo')">重做</n-button>
        <span>{{ dirty ? '未保存' : '已保存' }}</span>
        <n-button class="save-notes" type="primary" :loading="working" :disabled="!dirty || running" @click="save">保存并更新谱面</n-button>
      </div>
    </header>
    <section class="roll-panel">
      <n-alert v-if="error" type="error" closable @close="error = ''">{{ error }}<n-button size="small" @click="load">{{ dirty ? '放弃修改并重新载入' : '重新载入音符' }}</n-button></n-alert>
      <p v-if="loading" role="status">正在读取音符…</p>
      <div class="roll-toolbar"><strong>{{ mode === 'notes' ? '音符时间图' : '片段对照' }}</strong><n-button size="small" :disabled="!session || mode !== 'notes'" @click="add">添加音符</n-button><div class="roll-options"><label><input v-model="snap" type="checkbox" /> 吸附 1/16</label><button aria-label="放大时间图" @click="windowSize = Math.max(1.5, windowSize / 2)">＋</button><button aria-label="缩小时间图" @click="windowSize = Math.min(24, windowSize * 2)">−</button></div></div>
      <div class="event-window"><button aria-label="前六秒" @click="shiftWindow(-1)">‹</button><span>{{ windowStart.toFixed(1) }} – {{ (windowStart + windowSize).toFixed(1) }} 秒</span><button aria-label="后六秒" @click="shiftWindow(1)">›</button></div>
      <div class="time-ruler"><span v-for="(t, i) in gridTimes" :key="i">{{ t.toFixed(1) }}</span></div>
      <div v-if="mode === 'partial'" class="waveform-strip">
        <n-button v-if="!waveform.length" size="small" :loading="waveformLoading" @click="loadWaveform">载入原音波形</n-button><small v-if="waveformError">{{ waveformError }}</small>
        <svg v-if="waveform.length" viewBox="0 0 1000 70" preserveAspectRatio="none" aria-label="原音波形，拖动选择片段" @pointerdown="selectRange">
          <line v-for="(peak, i) in waveform" :key="i" :x1="i / waveform.length * 1000" :x2="i / waveform.length * 1000" :y1="35 - peak * 30" :y2="35 + peak * 30" stroke="#4c9d8b" stroke-width="0.8" />
          <rect :x="rangeStart / (session?.duration || 1) * 1000" y="0" :width="(rangeEnd - rangeStart) / (session?.duration || 1) * 1000" height="70" fill="#d49f45" opacity="0.25" pointer-events="none" />
        </svg>
      </div>
      <div class="roll-scroll">
        <div class="keyboard"><div v-for="pitch in rows" :key="pitch" :class="{ black: blackKey(pitch) }"><span>{{ pitch % 12 === 0 ? pitchLabel(pitch) : '' }}</span></div></div>
        <svg class="piano-roll" :viewBox="`0 0 1000 ${rollHeight}`" :style="{ height: rollHeight + 'px' }" preserveAspectRatio="none" aria-label="音符时间预览" @pointerdown="selectRange">
          <rect v-for="(pitch, i) in rows" :key="'r' + pitch" x="0" :y="i * 18" width="1000" height="18" :fill="blackKey(pitch) ? '#f4f7f8' : '#ffffff'" stroke="#e9eeee" stroke-width="0.5" />
          <line v-for="i in 25" :key="'g' + i" :x1="(i - 1) * 1000 / 24" :x2="(i - 1) * 1000 / 24" y1="0" :y2="rollHeight" :stroke="(i - 1) % 4 === 0 ? '#ccd9d6' : '#e7eeeb'" />
          <rect v-if="mode === 'partial'" :x="(rangeStart - windowStart) / windowSize * 1000" y="0" :width="Math.max(0, (rangeEnd - rangeStart) / windowSize * 1000)" :height="rollHeight" fill="#30937e" opacity="0.12" pointer-events="none" />
          <g v-for="n in visible" :key="n.id">
            <rect :x="(n.start - windowStart) / windowSize * 1000" :y="(pitches.max - n.pitch) * 18 + 2" :width="Math.max(5, (n.end - n.start) / windowSize * 1000)" height="14" rx="3" :fill="n.id === selected ? '#d39b3e' : n.hand === 'left' ? '#879bc2' : '#45a28c'" role="button" :aria-label="`${pitchLabel(n.pitch)}，${n.start.toFixed(2)} 秒`" tabindex="0" @pointerdown="dragNote($event, n)" @keydown.enter="select(n)" />
            <rect v-if="n.id === selected" :x="(n.end - windowStart) / windowSize * 1000 - 5" :y="(pitches.max - n.pitch) * 18 + 2" width="8" height="14" rx="3" fill="#fff4d7" stroke="#b78025" class="resize-handle" @pointerdown.stop="dragNote($event, n, true)" />
          </g>
          <rect v-for="n in (mode === 'partial' ? result?.notes || [] : [])" :key="'new' + n.id" :x="(n.start - windowStart) / windowSize * 1000" :y="(pitches.max - n.pitch) * 18 + 2" :width="Math.max(5, (n.end - n.start) / windowSize * 1000)" height="14" rx="3" fill="#d39b3e" fill-opacity="0.4" stroke="#bc832b" pointer-events="none" />
          <line v-if="current >= windowStart && current <= windowStart + windowSize" :x1="(current - windowStart) / windowSize * 1000" :x2="(current - windowStart) / windowSize * 1000" y1="0" :y2="rollHeight" stroke="#187a68" stroke-width="2" pointer-events="none" />
        </svg>
      </div>
      <div class="roll-legend"><span>● 右手</span><span>● 左手</span><span>{{ mode === 'notes' ? '拖动调整音高与位置 · 拖动右边缘调整时长' : '拖动框选原音时间段 · 金色为重新识别结果' }}</span></div>
    </section>
    <section v-if="mode === 'notes'" class="note-mode"><h3>选中音符</h3>
<div v-if="form" class="note-fields"><div class="selected-pitch">{{ pitchLabel(form.pitch) }}<small>选中音符 · MIDI {{ form.pitch }}</small></div>
          <label
            >音高 <span class="pitch-name">{{ pitchLabel(form.pitch || 60) }}</span
            ><n-input-number
              v-model:value="form.pitch"
              aria-label="音高 MIDI"
              :min="21"
              :max="108"
              :precision="0"
              size="small"
          /></label>
          <label
            >开始（秒）<n-input-number
              v-model:value="form.start"
              :format="formatTime"
              aria-label="音符开始时间"
              :min="0"
              :max="3600"
              :step="0.05"
              :precision="4"
              size="small"
          /></label>
          <label
            >结束（秒）<n-input-number
              v-model:value="form.end"
              :format="formatTime"
              aria-label="音符结束时间"
              :min="0"
              :max="3600"
              :step="0.05"
              :precision="4"
              size="small"
          /></label>
          <div class="duration-presets">
            <span>时值</span
            ><button
              v-for="[label, value] in [
                ['十六分', 0.25],
                ['八分', 0.5],
                ['四分', 1],
                ['二分', 2],
              ]"
              :key="String(label)"
              @click="setDuration(Number(value))"
            >
              {{ label }}
            </button>
          </div>
          <label
            >归属<n-select
              aria-label="音符左右手"
              size="small"
              :options="[
                { label: '自动分配', value: 'auto' },
                { label: '右手', value: 'right' },
                { label: '左手', value: 'left' },
              ]"
              :value="form.hand || 'auto'"
              @update:value="updateHand"
          /></label>
          <label>力度<n-slider v-model:value="form.velocity" :min="1" :max="127" aria-label="音符力度" /></label><n-button size="small" :disabled="!formDirty" @click="updateSelected">更新音符</n-button>
        </div>
        <p v-if="!form" class="empty-selection">点击乐谱或时间图中的音符<br />在此调整音高、时值与力度</p>
<n-button :disabled="!selected" @click="remove">删除选中</n-button>
<details class="event-details"><summary>音符事件列表</summary><div class="event-list" role="list" aria-label="音符事件列表"><button v-for="n in visible" :key="n.id" :class="{ selected: n.id === selected }" @click="select(n)"><b>{{ pitchLabel(n.pitch) }}</b><span>{{ n.start.toFixed(2) }} – {{ n.end.toFixed(2) }} s</span></button></div></details>
</section><section v-if="mode === 'partial' && session" class="partial-mode">
        <p class="editor-hint">
          按原录音时间选择片段。识别结果先预览，确认后替换；片段外的音符保留。
        </p>
        <label
          >片段开始（秒）<n-input-number
            v-model:value="rangeStart"
            aria-label="片段开始时间"
            :min="0"
            :max="session.duration"
            :precision="3"
            :step="0.1"
            :disabled="running || !!result"
        /></label>
        <label
          >片段结束（秒）<n-input-number
            v-model:value="rangeEnd"
            aria-label="片段结束时间"
            :min="0"
            :max="session.duration"
            :precision="3"
            :step="0.1"
            :disabled="running || !!result"
        /></label>
        <div class="range-actions">
          <n-button size="small" :disabled="running || !!result" @click="markRange('start')"
            >当前位置设为开始</n-button
          ><n-button size="small" :disabled="running || !!result" @click="markRange('end')"
            >设为结束</n-button
          >
        </div>
        <n-button
          size="small"
          :disabled="rangeEnd <= rangeStart"
          @click="emit('listen-range', { start: rangeStart, end: rangeEnd })"
          >试听所选原音</n-button
        >
        <n-button
          type="primary"
          :loading="working || running"
          :disabled="dirty || !!result"
          @click="beginPartial"
          >重新识别片段</n-button
        >
        <div v-if="task" class="partial-status" role="status">
          {{ stage }} <span v-if="task.progress != null">{{ Math.round(task.progress) }}%</span>
        </div>
        <template v-if="result">
          <div class="result-summary">
            <span
              >原片段 <b>{{ result.old_note_count }}</b> 音符</span
            ><span
              >新结果 <b>{{ result.notes.length }}</b> 音符</span
            >
          </div>
          <p class="editor-hint">
            替换按音符起点划分；选择前已经按住的长音会保留。新音符止于所选片段末尾。
          </p>
          <n-alert v-if="staleResult" type="warning"
            >曲目在识别后已修改，请放弃该结果，再按当前版本识别。</n-alert
          >
          <div class="event-list">
            <div v-for="n in result.notes.slice(0, 80)" :key="n.id" class="preview-event">
              <b>{{ pitchLabel(n.pitch) }}</b
              ><span>{{ n.start.toFixed(2) }} – {{ n.end.toFixed(2) }} s</span>
            </div>
            <p v-if="!result.notes.length">新结果未识别到音符，应用后会移除该片段内起奏的音符。</p>
          </div>
          <n-button
            type="primary"
            :disabled="!!staleResult || dirty"
            :loading="working"
            @click="apply"
            >应用替换结果</n-button
          >
          <n-button @click="discardPartial">放弃结果</n-button>
        </template>
        <n-button v-else-if="task?.status === 'failed'" size="small" @click="discardPartial"
          >清除此任务</n-button
        >
        <small v-if="dirty" class="editor-hint">请先保存或撤销音符修改，再重新识别。</small>
      </section>
  </aside>
</template>

<style scoped>
.note-editor {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  overflow: auto;
  padding: 16px;
  background: #fff;
  border: 1px solid #e2e9ed;
  border-radius: 14px;
  color: #2c414b;
  font-size: 12px;
  scrollbar-width: thin;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
}
.close-editor {
  border: 0;
  background: transparent;
  color: #7a8e92;
  font-size: 23px;
  cursor: pointer;
}
.editor-tabs {
  display: flex;
  gap: 4px;
  background: #f0f5f3;
  border-radius: 9px;
  padding: 4px;
}
.editor-tabs button {
  flex: 1;
  padding: 8px 5px;
  border: 0;
  border-radius: 6px;
  color: #6d817d;
  background: transparent;
  cursor: pointer;
}
.editor-tabs button.active {
  color: #27735e;
  background: #fff;
  box-shadow: 0 1px 4px #263b3212;
}
.editor-hint {
  margin: 0;
  color: #7a8b90;
  line-height: 1.7;
  font-size: 11px;
}
.note-mode,
.partial-mode {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}
.editor-history,
.note-actions,
.range-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.editor-history span {
  margin-left: auto;
  color: #a77a39;
  font-size: 11px;
}
.event-window {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #778c86;
}
.event-window button {
  width: 28px;
  height: 25px;
  border: 1px solid #e0eae5;
  border-radius: 6px;
  background: #fff;
  color: #527c6c;
  cursor: pointer;
}
.piano-roll {
  width: 100%;
  min-height: 110px;
  flex: none;
  background: #f4f8f6;
  border: 1px solid #e5eee8;
  border-radius: 8px;
  overflow: hidden;
}
.piano-roll rect {
  cursor: pointer;
}
.note-fields {
  display: grid;
  gap: 10px;
  padding: 12px;
  background: #f8faf8;
  border: 1px solid #e8eee9;
  border-radius: 10px;
}
.note-fields label,
.partial-mode > label {
  display: grid;
  grid-template-columns: 95px 1fr;
  align-items: center;
  gap: 8px;
}
.pitch-name {
  color: #a77a39;
  font-weight: 650;
}
.note-fields label:first-child {
  grid-template-columns: 34px 45px 1fr;
}
.duration-presets {
  display: flex;
  gap: 5px;
  align-items: center;
  flex-wrap: wrap;
}
.duration-presets button {
  border: 1px solid #dde8e1;
  background: #fff;
  border-radius: 5px;
  padding: 4px;
  color: #5f7b6e;
  cursor: pointer;
}
.event-list {
  max-height: 180px;
  overflow: auto;
  border: 1px solid #e7eeea;
  border-radius: 8px;
  scrollbar-width: thin;
}
.event-list button,
.preview-event {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  background: #fff;
  border: 0;
  border-bottom: 1px solid #f1f5f2;
  text-align: left;
  font-size: 11px;
  color: #60766d;
}
.event-list button {
  cursor: pointer;
}
.event-list button:hover {
  background: #f5f8f5;
}
.event-list button.selected {
  background: #edf4e9;
  color: #8e642d;
}
.event-list b {
  min-width: 34px;
  color: #3a5547;
}
.event-list small {
  margin-left: auto;
  color: #91a096;
}
.event-list p {
  padding: 10px;
  margin: 0;
  font-size: 11px;
  line-height: 1.6;
  color: #82958b;
}
.save-notes {
  margin-top: 2px;
  flex: none;
}
.partial-status {
  padding: 10px;
  border-radius: 8px;
  background: #eef6f2;
  color: #3c7b63;
}
.result-summary {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: #f8f4ec;
  border-radius: 8px;
  color: #8d6c3e;
}
.result-summary b {
  font-size: 18px;
}
.preview-event {
  color: #718678;
}
@media (max-width: 1100px) {
  .note-editor {
    max-height: 300px;
  }
  .note-mode {
    display: grid;
    grid-template-columns: 1fr 1fr;
    align-items: start;
  }
  .note-mode > .editor-hint,
  .editor-history,
  .save-notes {
    grid-column: 1/-1;
  }
  .note-fields {
    grid-row: 3/6;
    grid-column: 2;
  }
  .event-list {
    max-height: 135px;
  }
  .piano-roll {
    grid-column: 1;
  }
  .partial-mode {
    display: grid;
    grid-template-columns: 1fr 1fr;
    align-items: start;
  }
  .partial-mode > .editor-hint,
  .partial-mode > .event-list,
  .partial-mode > .result-summary {
    grid-column: 1/-1;
  }
}

.waveform-strip { margin: 4px 16px 4px 64px; flex: none; }
.waveform-strip svg { display: block; width: 100%; height: 70px; background: #f5f9f7; border-radius: 6px; touch-action: none; cursor: crosshair; }
/* The editor participates in the reader grid so the existing score player stays mounted. */
.note-editor { display: contents; font-size: 14px; }
.correction-header { grid-column: 1 / -1; grid-row: 1; display: flex; gap: 18px; min-width: 0; background: white; border-radius: 12px; padding: 10px 16px; }
.back-reader { white-space: nowrap; background: none; border: 0; color: #344d55; font-size: 15px; cursor: pointer; }
.editor-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 27vw; font-family: Georgia, serif; font-size: 19px; }
.editor-tabs { margin-left: auto; min-width: 250px; }
.editor-history { flex-wrap: nowrap; }
.editor-history span { white-space: nowrap; }
.save-notes { margin: 0; }
.roll-panel { grid-column: 1; grid-row: 3; min-width: 0; min-height: 0; display: flex; flex-direction: column; border: 1px solid #e0e8e6; border-radius: 12px; background: white; overflow: hidden; }
.roll-toolbar { display: flex; gap: 16px; align-items: center; padding: 12px 16px; border-bottom: 1px solid #edf1ef; }
.roll-options { margin-left: auto; display: flex; gap: 12px; align-items: center; color: #71857e; }
.roll-options button { border: 0; background: #f0f6f3; border-radius: 5px; cursor: pointer; }
.event-window { padding: 5px 16px; }
.time-ruler { margin-left: 64px; display: flex; justify-content: space-between; padding-right: 16px; font-size: 11px; color: #7b8e88; }
.roll-scroll { overflow: auto; flex: 1; min-height: 0; position: relative; display: flex; align-items: flex-start; overscroll-behavior: contain; }
.keyboard { width: 64px; flex: none; position: sticky; left: 0; z-index: 1; background: white; }
.keyboard > div { height: 18px; box-sizing: border-box; border: 1px solid #e0e6e4; font-size: 10px; text-align: right; padding-right: 6px; }
.keyboard > div.black { background: linear-gradient(90deg,#38423f 65%, white 65%); }
.piano-roll { flex: 1; width: calc(100% - 64px); min-width: 0; min-height: 0; border: 0; border-radius: 0; touch-action: none; user-select: none; }
.piano-roll rect { cursor: grab; }
.piano-roll .resize-handle { cursor: ew-resize; }
.roll-legend { display: flex; gap: 20px; color: #45a28c; padding: 8px 16px; font-size: 11px; border-top: 1px solid #edf1ef; }
.roll-legend span:nth-child(2) { color: #879bc2; }
.roll-legend span:last-child { margin-left: auto; color: #8a9995; }
.note-mode, .partial-mode { grid-column: 2; grid-row: 2 / 4; display: flex; flex-direction: column; gap: 18px; padding: 22px; background: white; border: 1px solid #e0e8e6; border-radius: 12px; overflow: auto; min-height: 0; }
.note-mode h3 { margin: 0; font-size: 16px; }
.note-fields { display: flex; flex-direction: column; padding: 0; background: none; border: 0; gap: 20px; }
.note-fields label, .note-fields label:first-child { display: grid; grid-template-columns: 70px minmax(0,1fr); font-size: 13px; }
.note-fields label:first-of-type .pitch-name { display: none; }
.selected-pitch { color: #16775f; font-size: 44px; font-family: Georgia, serif; line-height: 1.3; }
.selected-pitch small { display: block; font-family: inherit; font-size: 12px; color: #8a9c95; margin-top: 4px; }
.empty-selection { color: #879a92; line-height: 2; padding: 30px 0; }
.event-details { font-size: 12px; color: #789086; }
.event-details summary { cursor: pointer; margin-bottom: 12px; }
.partial-mode .editor-hint { font-size: 13px; }
@media (max-width: 1100px) {
 .editor-title { display: none; }
 .editor-tabs { min-width: 210px; margin-left: 0; }
 .correction-header { gap: 8px; padding: 8px; }
 .editor-history { margin-left: auto; gap: 4px; }
 .editor-history span { display: none; }
 .note-mode, .partial-mode { padding: 14px; }
 .roll-legend span:last-child { display: none; }
}
</style>
